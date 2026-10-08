#!/usr/bin/env bash
# Instala o APK no emulador, abre o aplicativo e confere que o servidor Python sobe e responde.
set -uo pipefail
APK="$1"

adb wait-for-device
adb install -r "$APK" || { echo "Falha ao instalar o APK"; exit 1; }
adb logcat -c
adb shell am start -n br.com.notaxml/.MainActivity
adb forward tcp:18765 tcp:18765

ok=""
for i in $(seq 1 90); do
  if [ "$(curl -s -m 3 http://127.0.0.1:18765/saude || true)" = "notaxml" ]; then ok=1; break; fi
  sleep 3
done

adb logcat -d -s python.stdout:I python.stderr:I NotaXML:E AndroidRuntime:E > logcat.txt
echo "=============== logcat (Python e erros) ==============="
tail -80 logcat.txt
echo "======================================================="

[ -n "$ok" ] || { echo "ERRO: o servidor não respondeu em 4,5 minutos"; exit 1; }
grep -q "NOTAXML-AUTOTESTE: ok" logcat.txt || { echo "ERRO: o autoteste das bibliotecas não passou"; exit 1; }

# sem o segredo do aplicativo (como faria outro app do celular), o acesso cai na tela de login
codigo=$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:18765/configuracao)
[ "$codigo" = "302" ] || { echo "ERRO: /configuracao devia redirecionar ao login, veio HTTP $codigo"; exit 1; }
echo "Aplicativo Android OK"
