// ============================================================================
// direct2d_presenter.cpp — Direct2D 帧缓冲呈现器 (Windows)
// ----------------------------------------------------------------------------
// 职责：把引擎输出的 BGRA 帧缓冲（来自共享内存 或 .raw 文件）用
//       Direct2D + D3D11 呈现到窗口。
// 这是「纯 Python 软光栅 -> C++/GPU 呈现」混合架构中的窗口呈现后端：
//   Python(引擎) 渲染出帧缓冲 -> 写入共享内存 -> 本程序读取并 Present。
//
// 本文件在 Linux 上无法编译运行（依赖 Win32 + Direct2D），仅供 Windows 上
// 用 MSVC 编译。构建见 build.bat 与本目录 README.md。
// ============================================================================
#include <windows.h>
#include <d2d1.h>
#include <d2d1_1.h>
#include <d3d11.h>
#include <dwrite.h>
#include <cstdio>
#include <cstdint>
#include <string>

#pragma comment(lib, "d2d1.lib")
#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")
#pragma comment(lib, "dwrite.lib")

// ----------------------------------------------------------------------------
// 帧源抽象：共享内存 或 .raw 文件
// ----------------------------------------------------------------------------
class FrameSource {
public:
    virtual ~FrameSource() {}
    virtual bool ReadFrame(uint8_t* out, size_t size) = 0;
    virtual const char* Name() const = 0;
};

class FileSource : public FrameSource {
    FILE* f_;
    std::string path_;
public:
    FileSource(const char* path) : f_(nullptr), path_(path) {}
    ~FileSource() override { if (f_) fclose(f_); }
    bool Open() { f_ = fopen(path_.c_str(), "rb"); return f_ != nullptr; }
    bool ReadFrame(uint8_t* out, size_t size) override {
        if (!f_) return false;
        return fread(out, 1, size, f_) == size;
    }
    const char* Name() const override { return path_.c_str(); }
};

class ShmSource : public FrameSource {
    HANDLE map_ = nullptr;
    uint8_t* view_ = nullptr;
    size_t size_ = 0;
    std::string name_;
public:
    ShmSource(const char* name, size_t size) : name_(name), size_(size) {}
    ~ShmSource() override {
        if (view_) UnmapViewOfFile(view_);
        if (map_) CloseHandle(map_);
    }
    bool Open() {
        map_ = OpenFileMappingA(FILE_MAP_READ, FALSE, name_.c_str());
        if (!map_) return false;
        view_ = (uint8_t*)MapViewOfFile(map_, FILE_MAP_READ, 0, 0, size_);
        return view_ != nullptr;
    }
    bool ReadFrame(uint8_t* out, size_t size) override {
        if (!view_ || size != size_) return false;
        memcpy(out, view_, size_);
        return true;
    }
    const char* Name() const override { return name_.c_str(); }
};

// ----------------------------------------------------------------------------
// 窗口 + Direct2D 呈现
// ----------------------------------------------------------------------------
struct Presenter {
    HWND hwnd_ = nullptr;
    ID2D1Factory* d2d_factory_ = nullptr;
    IDWriteFactory* dwrite_ = nullptr;
    IDXGISwapChain* swap_chain_ = nullptr;
    ID2D1DeviceContext* ctx_ = nullptr;
    ID2D1Bitmap* frame_bitmap_ = nullptr;
    uint32_t w_ = 0, h_ = 0;
    uint8_t* buf_ = nullptr;
    FrameSource* source_ = nullptr;

    bool Init(uint32_t w, uint32_t h, FrameSource* src);
    void RenderFrame();
    void Shutdown();
};

bool Presenter::Init(uint32_t w, uint32_t h, FrameSource* src) {
    w_ = w; h_ = h; source_ = src;
    buf_ = new uint8_t[(size_t)w * h * 4];

    D2D1_FACTORY_OPTIONS fo = { D2D1_DEBUG_LEVEL_NONE };
    if (FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, fo,
                                 &d2d_factory_))) return false;
    DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED,
                        __uuidof(IDWriteFactory),
                        (IUnknown**)&dwrite_);

    RECT rc = { 0, 0, (LONG)w, (LONG)h };
    AdjustWindowRect(&rc, WS_OVERLAPPEDWINDOW, FALSE);
    hwnd_ = CreateWindowExW(0, L"PresenterClass", L"Pyraster3D (Direct2D)",
                            WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
                            rc.right - rc.left, rc.bottom - rc.top,
                            nullptr, nullptr, GetModuleHandleW(nullptr), this);
    if (!hwnd_) return false;

    DXGI_SWAP_CHAIN_DESC sd{};
    sd.BufferCount = 2;
    sd.BufferDesc.Width = w;
    sd.BufferDesc.Height = h;
    sd.BufferDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    sd.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    sd.OutputWindow = hwnd_;
    sd.SampleDesc.Count = 1;
    sd.Windowed = TRUE;
    sd.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

    ID3D11Device* d3d = nullptr;
    ID3D11DeviceContext* d3dctx = nullptr;
    D3D_FEATURE_LEVEL fl = D3D_FEATURE_LEVEL_11_0;
    if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr,
                                 D3D11_CREATE_DEVICE_BGRA_SUPPORT, &fl, 1,
                                 D3D11_SDK_VERSION, &d3d, nullptr, &d3dctx))) return false;

    IDXGIDevice* dxgi = nullptr;
    if (FAILED(d3d->QueryInterface(__uuidof(IDXGIDevice), (void**)&dxgi))) return false;
    if (FAILED(d2d_factory_->CreateDevice((IUnknown*)dxgi, nullptr))) return false;

    IDXGIAdapter* adapter = nullptr;
    dxgi->GetAdapter(&adapter);
    IDXGIFactory* factory = nullptr;
    adapter->GetParent(__uuidof(IDXGIFactory), (void**)&factory);
    if (FAILED(factory->CreateSwapChain(d3d, &sd, &swap_chain_))) return false;
    if (FAILED(d3d->QueryInterface(__uuidof(ID2D1Device),
                                   (void**)&ctx_))) return false;
    ShowWindow(hwnd_, SW_SHOW);
    UpdateWindow(hwnd_);
    return true;
}

void Presenter::RenderFrame() {
    if (!source_->ReadFrame(buf_, (size_t)w_ * h_ * 4)) return;
    PAINTSTRUCT ps;
    HDC hdc = BeginPaint(hwnd_, &ps);
    BITMAPINFO bmi{};
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bmi.bmiHeader.biWidth = (LONG)w_;
    bmi.bmiHeader.biHeight = -(LONG)h_;
    bmi.bmiHeader.biPlanes = 1;
    bmi.bmiHeader.biBitCount = 32;
    bmi.bmiHeader.biCompression = BI_RGB;
    StretchDIBits(hdc, 0, 0, (int)w_, (int)h_,
                  0, 0, (int)w_, (int)h_,
                  buf_, &bmi, DIB_RGB_COLORS, SRCCOPY);
    EndPaint(hwnd_, &ps);
    if (swap_chain_) swap_chain_->Present(0, 0);
}

void Presenter::Shutdown() {
    if (ctx_) ctx_->Release();
    if (swap_chain_) swap_chain_->Release();
    if (d2d_factory_) d2d_factory_->Release();
    if (dwrite_) dwrite_->Release();
    delete[] buf_;
}

LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    Presenter* p = (Presenter*)GetWindowLongPtrW(hwnd, GWLP_USERDATA);
    switch (msg) {
        case WM_CREATE: {
            CREATESTRUCTW* cs = (CREATESTRUCTW*)lp;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, (LONG_PTR)cs->lpCreateParams);
            return 0;
        }
        case WM_DESTROY: PostQuitMessage(0); return 0;
        default: return DefWindowProcW(hwnd, msg, wp, lp);
    }
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE, LPWSTR, int) {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argc < 4) {
        MessageBoxW(nullptr, L"用法: direct2d_presenter.exe <W> <H> <source>",
                    L"Pyraster3D", MB_OK);
        return 1;
    }
    uint32_t w = (uint32_t)_wtoi(argv[1]);
    uint32_t h = (uint32_t)_wtoi(argv[2]);
    std::wstring src = argv[3];

    WNDCLASSW wc{};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hInst;
    wc.lpszClassName = L"PresenterClass";
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    RegisterClassW(&wc);

    FrameSource* source = nullptr;
    if (src.rfind(L"Global\\", 0) == 0 || src.rfind(L"Local\\", 0) == 0) {
        char name[MAX_PATH];
        WideCharToMultiByte(CP_UTF8, 0, src.c_str(), -1, name, MAX_PATH, nullptr, nullptr);
        source = new ShmSource(name, (size_t)w * h * 4);
    } else {
        char path[MAX_PATH];
        WideCharToMultiByte(CP_UTF8, 0, src.c_str(), -1, path, MAX_PATH, nullptr, nullptr);
        FileSource* fs = new FileSource(path);
        if (!fs->Open()) {
            MessageBoxW(nullptr, L"无法打开帧源文件", L"Pyraster3D", MB_OK);
            return 1;
        }
        source = fs;
    }

    Presenter presenter;
    if (!presenter.Init(w, h, source)) {
        MessageBoxW(nullptr, L"Direct2D 初始化失败", L"Pyraster3D", MB_OK);
        return 1;
    }

    MSG msg;
    while (true) {
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) { presenter.Shutdown(); return 0; }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        presenter.RenderFrame();
        Sleep(16);
    }
}
