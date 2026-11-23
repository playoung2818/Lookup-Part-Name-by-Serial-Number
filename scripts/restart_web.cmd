@echo off
rem Restart the web app the right way (desktop sign-in, with QuickBooks share access).
rem Safe to run from SSH. See scripts\start_web_desktop.ps1.
type nul > "%~dp0..\restart.request"
schtasks /run /tn "Receiving Log Web App (desktop)"
echo Restart requested. Status: see web.watchdog.log in the project folder (takes about 10 seconds).
