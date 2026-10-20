package com.remotepad

import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class ConnectActivity : AppCompatActivity() {

    private lateinit var etIpAddress: EditText
    private lateinit var etPort: EditText
    private lateinit var btnConnect: Button
    private lateinit var tvStatus: TextView
    private lateinit var sharedPreferences: SharedPreferences

    companion object {
        private const val PREFS_NAME = "remote_gamepad_prefs"
        private const val KEY_LAST_IP = "last_ip_address"
        private const val KEY_LAST_PORT = "last_port"
        const val EXTRA_HOST = "host"
        const val EXTRA_PORT = "port"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_connect)

        sharedPreferences = getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        etIpAddress = findViewById(R.id.etIpAddress)
        etPort = findViewById(R.id.etPort)
        btnConnect = findViewById(R.id.btnConnect)
        tvStatus = findViewById(R.id.tvStatus)

        // Restore last used IP & Port
        val lastIp = sharedPreferences.getString(KEY_LAST_IP, "")
        if (!lastIp.isNullOrEmpty()) {
            etIpAddress.setText(lastIp)
            etIpAddress.setSelection(lastIp.length)
        }

        val lastPort = sharedPreferences.getString(KEY_LAST_PORT, "8888") ?: "8888"
        etPort.setText(lastPort)

        btnConnect.setOnClickListener {
            val ip = etIpAddress.text.toString().trim()
            var port = etPort.text.toString().trim()

            if (ip.isEmpty()) {
                tvStatus.text = getString(R.string.status_invalid_ip)
                tvStatus.setTextColor(ContextCompat.getColor(this, R.color.red))
                etIpAddress.requestFocus()
                return@setOnClickListener
            }

            if (port.isEmpty()) {
                port = "8888"
            }

            // Save IP and Port in SharedPreferences
            sharedPreferences.edit()
                .putString(KEY_LAST_IP, ip)
                .putString(KEY_LAST_PORT, port)
                .apply()

            tvStatus.text = getString(R.string.status_connecting)
            tvStatus.setTextColor(ContextCompat.getColor(this, R.color.green))

            // Start GamepadActivity
            val intent = Intent(this, GamepadActivity::class.java).apply {
                putExtra(EXTRA_HOST, ip)
                putExtra(EXTRA_PORT, port)
            }
            startActivity(intent)
        }
    }

    override fun onResume() {
        super.onResume()
        // Reset status message when returning from GamepadActivity
        tvStatus.text = getString(R.string.status_ready)
        tvStatus.setTextColor(ContextCompat.getColor(this, R.color.text_secondary))
    }
}
