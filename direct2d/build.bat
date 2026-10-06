@echo off
REM ============================================================================
REM build.bat — 在 Windows 上用 MSVC 编译 Direct2D 呈现后端
REM ============================================================================
REM 前置条件：
REM   1. 本机已安装 Visual Studio 2022 (含「使用 C++ 的桌面开发」工作负载)
REM   2. 在「VS x64 Native Tools Command Prompt」中运行本脚本
REM 产物：direct2d_presenter.exe
REM ============================================================================
setlocal

if not defined VSCMD_ARG_TGT_ARCH (
    echo [ERROR] 请先在 "VS x64 Native Tools Command Prompt" 中运行本脚本
    exit /b 1
)

cl /nologo /O2 /EHsc /MD /std:c++17 ^
   /I "%WindowsSdkDir%Include\um" /I "%WindowsSdkDir%Include\shared" ^
   direct2d_presenter.cpp ^
   /link /out:direct2d_presenter.exe d2d1.lib d3d11.lib dxgi.lib dwrite.lib

if exist direct2d_presenter.exe (
    echo [OK] 已生成 direct2d_presenter.exe
) else (
    echo [ERROR] 编译失败
)
endlocal
