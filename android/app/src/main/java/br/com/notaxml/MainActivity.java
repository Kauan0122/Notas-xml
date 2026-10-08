package br.com.notaxml;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Mostra a tela do NotaXML (que roda dentro do próprio aplicativo) numa WebView. */
public class MainActivity extends Activity {
    private static final int PEDIDO_ARQUIVO = 1001;
    private static final int PEDIDO_NOTIFICACAO = 1002;

    private WebView web;
    private TextView aviso;
    private ValueCallback<Uri[]> escolhaDeArquivo;

    @Override
    protected void onCreate(Bundle estado) {
        super.onCreate(estado);

        FrameLayout raiz = new FrameLayout(this);
        raiz.setBackgroundColor(Color.WHITE);
        // Android 15 desenha o app por baixo das barras do sistema: o conteúdo precisa respeitar as margens
        // (barra de status, barra de gestos e teclado), senão o relógio cobre o cabeçalho.
        raiz.setOnApplyWindowInsetsListener(this::ajustarMargens);
        web = new WebView(this);
        aviso = new TextView(this);
        aviso.setText("Iniciando o NotaXML…\nNa primeira vez isso pode levar um minuto.");
        aviso.setGravity(Gravity.CENTER);
        aviso.setTextSize(18);
        aviso.setPadding(48, 48, 48, 48);
        raiz.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        raiz.addView(aviso, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(raiz);
        usarIconesEscurosNasBarras(); // só depois do setContentView: antes disso a janela ainda não existe

        configurarWebView();
        pedirPermissaoDeNotificacao();
        iniciarServico();
        esperarServidor();
    }

    /**
     * O Android 15 desenha o app por baixo das barras do sistema com ícones claros. Como o fundo do app é branco,
     * o relógio e os ícones sumiriam: pede ícones escuros na barra de status e na de gestos.
     */
    @SuppressWarnings("deprecation")
    private void usarIconesEscurosNasBarras() {
        try {
            aplicarIconesEscuros();
        } catch (RuntimeException indisponivel) {
            // detalhe visual: se este aparelho não permitir, o app segue funcionando
        }
    }

    @SuppressWarnings("deprecation")
    private void aplicarIconesEscuros() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controle = getWindow().getInsetsController();
            if (controle != null) {
                int claras = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                controle.setSystemBarsAppearance(claras, claras);
            }
        } else {
            View janela = getWindow().getDecorView();
            int opcoes = janela.getSystemUiVisibility() | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= 26) {
                opcoes |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }
            janela.setSystemUiVisibility(opcoes);
        }
    }

    @SuppressWarnings("deprecation")
    private WindowInsets ajustarMargens(View visao, WindowInsets margens) {
        int esquerda, topo, direita, base;
        if (Build.VERSION.SDK_INT >= 30) {
            android.graphics.Insets i = margens.getInsets(WindowInsets.Type.systemBars()
                    | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
            esquerda = i.left;
            topo = i.top;
            direita = i.right;
            base = i.bottom;
        } else {
            esquerda = margens.getSystemWindowInsetLeft();
            topo = margens.getSystemWindowInsetTop();
            direita = margens.getSystemWindowInsetRight();
            base = margens.getSystemWindowInsetBottom();
        }
        visao.setPadding(esquerda, topo, direita, base);
        return Build.VERSION.SDK_INT >= 30 ? WindowInsets.CONSUMED : margens.consumeSystemWindowInsets();
    }

    private void configurarWebView() {
        WebSettings ajustes = web.getSettings();
        ajustes.setJavaScriptEnabled(true);
        ajustes.setDomStorageEnabled(true);
        ajustes.setAllowFileAccess(false);
        ajustes.setBuiltInZoomControls(false);

        // O segredo vai num cookie: só este aplicativo o conhece, então só ele entra sem digitar a senha.
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setCookie(Configuracao.URL,
                Configuracao.COOKIE + "=" + Configuracao.segredo(this) + "; Path=/; HttpOnly");
        cookies.flush();

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest pedido) {
                Uri destino = pedido.getUrl();
                if ("127.0.0.1".equals(destino.getHost())) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, destino));
                } catch (ActivityNotFoundException ignorado) {
                    // sem aplicativo para abrir o endereço
                }
                return true;
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> retorno,
                                             FileChooserParams parametros) {
                if (escolhaDeArquivo != null) {
                    escolhaDeArquivo.onReceiveValue(null);
                }
                escolhaDeArquivo = retorno;
                Intent escolher = new Intent(Intent.ACTION_GET_CONTENT);
                escolher.addCategory(Intent.CATEGORY_OPENABLE);
                escolher.setType("*/*");
                try {
                    startActivityForResult(Intent.createChooser(escolher, "Escolher arquivo"), PEDIDO_ARQUIVO);
                } catch (ActivityNotFoundException erro) {
                    escolhaDeArquivo = null;
                    return false;
                }
                return true;
            }
        });

        // PDFs, XMLs, ZIPs e CSVs que o sistema manda baixar
        web.setDownloadListener((url, agente, disposicao, tipo, tamanho) -> baixar(url, disposicao, tipo));
    }

    @Override
    protected void onActivityResult(int pedido, int resultado, Intent dados) {
        super.onActivityResult(pedido, resultado, dados);
        if (pedido == PEDIDO_ARQUIVO && escolhaDeArquivo != null) {
            escolhaDeArquivo.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultado, dados));
            escolhaDeArquivo = null;
        }
    }

    private void pedirPermissaoDeNotificacao() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, PEDIDO_NOTIFICACAO);
        }
    }

    private void iniciarServico() {
        startForegroundService(new Intent(this, ServidorService.class));
    }

    @Override
    protected void onResume() {
        super.onResume();
        iniciarServico(); // se o Android encerrou o servidor em segundo plano, sobe de novo
    }

    /** Espera o servidor local responder e então abre a tela. */
    private void esperarServidor() {
        new Thread(() -> {
            long limite = System.currentTimeMillis() + 180_000;
            while (System.currentTimeMillis() < limite) {
                if (servidorResponde()) {
                    runOnUiThread(() -> {
                        web.loadUrl(Configuracao.URL + "/");
                        aviso.setVisibility(View.GONE);
                    });
                    return;
                }
                try {
                    Thread.sleep(700);
                } catch (InterruptedException interrompido) {
                    return;
                }
            }
            runOnUiThread(() -> aviso.setText("O NotaXML não iniciou.\nFeche o aplicativo e abra de novo."));
        }, "notaxml-espera").start();
    }

    private boolean servidorResponde() {
        try {
            HttpURLConnection conexao = (HttpURLConnection) new URL(Configuracao.URL + "/saude").openConnection();
            conexao.setConnectTimeout(1500);
            conexao.setReadTimeout(1500);
            try (BufferedReader leitor = new BufferedReader(new InputStreamReader(conexao.getInputStream()))) {
                return "notaxml".equals(leitor.readLine());
            }
        } catch (Exception indisponivel) {
            return false;
        }
    }

    /** Baixa o arquivo (com o cookie da sessão) para Downloads/NotaXML e abre se for PDF. */
    private void baixar(String url, String disposicao, String tipo) {
        new Thread(() -> {
            try {
                HttpURLConnection conexao = (HttpURLConnection) new URL(url).openConnection();
                String cookie = CookieManager.getInstance().getCookie(url);
                if (cookie != null) {
                    conexao.setRequestProperty("Cookie", cookie);
                }
                conexao.setConnectTimeout(15_000);
                conexao.setReadTimeout(120_000);
                if (conexao.getResponseCode() != 200) {
                    throw new IllegalStateException("HTTP " + conexao.getResponseCode());
                }
                String nome = URLUtil.guessFileName(url, disposicao, tipo);
                String mime = tipo == null ? "application/octet-stream" : tipo.split(";")[0].trim();

                ContentValues valores = new ContentValues();
                valores.put(MediaStore.MediaColumns.DISPLAY_NAME, nome);
                valores.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                valores.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/NotaXML");
                valores.put(MediaStore.MediaColumns.IS_PENDING, 1);
                Uri arquivo = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, valores);
                if (arquivo == null) {
                    throw new IllegalStateException("não foi possível criar o arquivo em Downloads");
                }
                try (InputStream entrada = conexao.getInputStream();
                     OutputStream saida = getContentResolver().openOutputStream(arquivo)) {
                    byte[] bloco = new byte[16 * 1024];
                    int lidos;
                    while ((lidos = entrada.read(bloco)) != -1) {
                        saida.write(bloco, 0, lidos);
                    }
                }
                valores.clear();
                valores.put(MediaStore.MediaColumns.IS_PENDING, 0);
                getContentResolver().update(arquivo, valores, null, null);

                runOnUiThread(() -> {
                    Toast.makeText(this, "Salvo em Downloads/NotaXML: " + nome, Toast.LENGTH_LONG).show();
                    if (mime.equals("application/pdf")) {
                        abrir(arquivo, mime);
                    }
                });
            } catch (Exception erro) {
                runOnUiThread(() -> Toast.makeText(this, "Não foi possível baixar: " + erro.getMessage(),
                        Toast.LENGTH_LONG).show());
            }
        }, "notaxml-download").start();
    }

    private void abrir(Uri arquivo, String tipo) {
        Intent abrir = new Intent(Intent.ACTION_VIEW);
        abrir.setDataAndType(arquivo, tipo);
        abrir.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(abrir);
        } catch (ActivityNotFoundException semLeitor) {
            Toast.makeText(this, "Instale um leitor de PDF para abrir o arquivo.", Toast.LENGTH_LONG).show();
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web.canGoBack()) {
            web.goBack();
        } else {
            moveTaskToBack(true); // o servidor continua rodando em segundo plano
        }
    }
}
