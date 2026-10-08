package br.com.notaxml;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

/** Mantém o servidor do NotaXML (Python) rodando dentro do aplicativo, mesmo com a tela fechada. */
public class ServidorService extends Service {
    private static final String TAG = "NotaXML";
    private static final String CANAL = "notaxml";
    private static final int ID_NOTIFICACAO = 1;
    private static boolean iniciado = false;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        criarCanal();
        Notification notificacao = new Notification.Builder(this, CANAL)
                .setSmallIcon(R.drawable.ic_notificacao)
                .setContentTitle("NotaXML")
                .setContentText("Servidor local em execução. Toque para abrir.")
                .setOngoing(true)
                .setContentIntent(PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                        PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
                .build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(ID_NOTIFICACAO, notificacao, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(ID_NOTIFICACAO, notificacao);
        }
        iniciarServidor();
        return START_STICKY;
    }

    private void criarCanal() {
        NotificationChannel canal = new NotificationChannel(CANAL, "NotaXML", NotificationManager.IMPORTANCE_LOW);
        getSystemService(NotificationManager.class).createNotificationChannel(canal);
    }

    private synchronized void iniciarServidor() {
        if (iniciado) {
            return;
        }
        iniciado = true;
        final String pasta = Configuracao.pasta(this);
        final String segredo = Configuracao.segredo(this);
        new Thread(() -> {
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(getApplicationContext()));
                }
                // só volta quando o servidor termina
                Python.getInstance().getModule("notaxml.android").callAttr("rodar", pasta, Configuracao.PORTA, segredo);
            } catch (Throwable erro) {
                Log.e(TAG, "Falha ao iniciar o servidor", erro);
            } finally {
                iniciado = false;
            }
        }, "notaxml-python").start();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
