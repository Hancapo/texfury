@echo off
setlocal

:: ── Locate Build Tools ───────────────────────────────────────────────────────
set "VCVARS=C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
    :: Fallback: try vswhere
    for /f "usebackq tokens=*" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2^>nul`) do set "VCVARS=%%i\VC\Auxiliary\Build\vcvars64.bat"
)
if not exist "%VCVARS%" (
    echo ERROR: Cannot find vcvars64.bat. Install VS Build Tools.
    exit /b 1
)

call "%VCVARS%" >nul 2>&1

:: ── Paths ────────────────────────────────────────────────────────────────────
set "VENDOR=%~dp0vendor"
set "STB=%VENDOR%\stb"
set "BC7=%VENDOR%\bc7enc_rdo"
set "OUT=%~dp0..\texfury"

:: ── Compile ──────────────────────────────────────────────────────────────────
echo Building texfury_native.dll ...

cl /nologo /LD /EHsc /O2 /DNDEBUG /DWIN32 /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS ^
   /DSUPPORT_BC7E=1 ^
   /std:c++17 ^
   /I"%STB%" /I"%BC7%" ^
   "%~dp0texfury_native.cpp" ^
   "%BC7%\rgbcx.cpp" "%BC7%\bc7decomp.cpp" "%BC7%\bc7decomp_ref.cpp" "%BC7%\bc7enc.cpp" ^
   "%BC7%\rdo_bc_encoder.cpp" "%BC7%\ert.cpp" "%BC7%\utils.cpp" "%BC7%\lodepng.cpp" ^
   "%BC7%\bc7e.obj" "%BC7%\bc7e_avx.obj" "%BC7%\bc7e_avx2.obj" ^
   "%BC7%\bc7e_sse2.obj" "%BC7%\bc7e_sse4.obj" ^
   /Fe:"%OUT%\texfury_native.dll" ^
   /link /DLL

if %ERRORLEVEL% NEQ 0 (
    echo BUILD FAILED
    exit /b 1
)

:: ── Cleanup ──────────────────────────────────────────────────────────────────
del /q "%~dp0*.obj" 2>nul
del /q "%OUT%\texfury_native.exp" 2>nul
del /q "%OUT%\texfury_native.lib" 2>nul

echo.
echo SUCCESS: texfury_native.dll built in %OUT%\
