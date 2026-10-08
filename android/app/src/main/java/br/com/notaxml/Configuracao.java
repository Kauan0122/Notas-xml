package br.com.notaxml;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.File;
import java.security.SecureRandom;

/** Valores compartilhados entre a tela e o serviço. */
final class Configuracao {
    /** Porta do servidor local. Escuta apenas em 127.0.0.1. */
    static final int PORTA = 18765;
    static final String URL = "http://127.0.0.1:" + PORTA;
    static final String COOKIE = "acesso_local";

    private static final String PREFS = "notaxml";
    private static final String CHAVE_SEGREDO = "segredo";

    private Configuracao() {
    }

    /**
     * Segredo aleatório, criado na primeira abertura e guardado no armazenamento privado do aplicativo. Outros
     * aplicativos do celular alcançam 127.0.0.1, mas não conhecem este valor.
     */
    static synchronized String segredo(Context contexto) {
        SharedPreferences prefs = contexto.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String segredo = prefs.getString(CHAVE_SEGREDO, null);
        if (segredo == null || segredo.length() < 32) {
            byte[] bytes = new byte[24];
            new SecureRandom().nextBytes(bytes);
            StringBuilder hex = new StringBuilder();
            for (byte b : bytes) {
                hex.append(String.format("%02x", b));
            }
            segredo = hex.toString();
            prefs.edit().putString(CHAVE_SEGREDO, segredo).apply();
        }
        return segredo;
    }

    /** Pasta da configuração, do certificado, do banco e dos XMLs (privada do aplicativo). */
    static String pasta(Context contexto) {
        return new File(contexto.getFilesDir(), "notaxml").getAbsolutePath();
    }
}
