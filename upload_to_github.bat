@echo off
echo ========================================
echo GitHub Upload Script
echo ========================================
echo.

REM Check if git is installed
git --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Git is not installed or not in PATH
    echo Please install Git from https://git-scm.com/
    pause
    exit /b 1
)

echo [1/5] Checking Git repository status...
if not exist .git (
    echo Initializing new Git repository...
    git init
    if errorlevel 1 (
        echo ERROR: Failed to initialize Git repository
        pause
        exit /b 1
    )
    echo Git repository initialized successfully!
) else (
    echo Git repository already exists.
)
echo.

echo [2/5] Checking current status...
git status --short
echo.

echo [3/5] Adding all files (respecting .gitignore)...
git add .
if errorlevel 1 (
    echo ERROR: Failed to add files
    pause
    exit /b 1
)
echo Files added successfully!
echo.

echo [4/5] Checking what will be committed...
git status --short
echo.

echo [5/5] Creating initial commit...
set /p commit_msg="Enter commit message (or press Enter for default): "
if "%commit_msg%"=="" set commit_msg=Initial commit: Satellite inference pipeline

git commit -m "%commit_msg%"
if errorlevel 1 (
    echo WARNING: Commit failed. This might be because:
    echo   - No changes to commit
    echo   - All files are already committed
    echo   - Or there was an error
    echo.
    git status
) else (
    echo Commit created successfully!
)
echo.

echo ========================================
echo Next Steps to Upload to GitHub:
echo ========================================
echo.
echo 1. Go to https://github.com and create a new repository
echo 2. Copy the repository URL (e.g., https://github.com/username/repo-name.git)
echo 3. Run these commands:
echo.
echo    git remote add origin YOUR_REPO_URL
echo    git branch -M main
echo    git push -u origin main
echo.
echo Or if you already have a remote:
echo    git remote set-url origin YOUR_REPO_URL
echo    git push -u origin main
echo.
echo ========================================
pause

