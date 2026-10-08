@echo off
rem Gera dist\NotaXML.exe no Windows. Requer Python 3.11+ instalado.
cd /d "%~dp0\.."
python -m venv .venv-build || goto erro
call .venv-build\Scripts\activate || goto erro
python -m pip install --upgrade pip || goto erro
pip install . pyinstaller pillow || goto erro
python empacotamento\gerar_icone.py || goto erro
pyinstaller --noconfirm --clean --onefile --console --name NotaXML ^
  --icon empacotamento\notaxml.ico --collect-data notaxml --collect-data brazilfiscalreport ^
  --collect-data fpdf --collect-data barcode ^
  empacotamento\NotaXML.py || goto erro
echo.
echo Pronto: dist\NotaXML.exe
exit /b 0
:erro
echo Falhou. Veja as mensagens acima.
exit /b 1
