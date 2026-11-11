@echo off
title ROSE - PMSE Estate Road & Accelerometer Analytics
echo Starting ROSE Local Application...
if exist "C:\Program Files\NVIDIA Corporation\Nsight Systems 2026.1.3\host-windows-x64\python\bin\python.exe" (
    "C:\Program Files\NVIDIA Corporation\Nsight Systems 2026.1.3\host-windows-x64\python\bin\python.exe" app.py
) else (
    python app.py
)
pause
