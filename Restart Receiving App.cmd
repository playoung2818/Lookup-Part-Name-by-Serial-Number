@echo off
rem Double-click on the server desktop (Remote Desktop) to restart the web app with
rem access to \\quickbook2024. Asks for administrator approval so it can also stop a copy
rem that was started from SSH. Do not run this over SSH.
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File \"%~dp0scripts\restart_app.ps1\"'"
