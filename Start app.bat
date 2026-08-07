@echo off
REM Double-click this to launch the IPUMS International explorer.
REM Streamlit apps cannot be started by running streamlit_app.py directly --
REM they need the "streamlit run" launcher, which starts a local web server.

cd /d "%~dp0"

echo Starting the IPUMS International explorer...
echo A browser tab will open at http://localhost:8501
echo Close this window (or press Ctrl+C) to stop the app.
echo.

python -m streamlit run streamlit_app.py

if errorlevel 1 (
    echo.
    echo ---------------------------------------------------------------
    echo The app failed to start. Common fixes:
    echo   1^) Install the dependencies:  pip install -e ".[app]"
    echo   2^) Build the catalog:         ipumsi refresh
    echo ---------------------------------------------------------------
)

echo.
pause
