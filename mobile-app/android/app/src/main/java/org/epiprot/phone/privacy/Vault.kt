package org.epiprot.phone.privacy

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Encryption at rest. One AES-256-GCM key lives in the Android Keystore (hardware-backed where the phone has it; it
 * never leaves the secure hardware and cannot be exported or backed up). It encrypts
 *  - the passphrase of the SQLCipher event log (random, created once),
 *  - personal settings (patient name, caregiver numbers, doctor e-mail, the name of the person deciding).
 * Reinstalling the app or "Delete all my data" makes the old data unreadable.
 */
object Vault {
    private const val ALIAS = "epiprot_vault_v1"
    private const val PREFIX = "v1:"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build())
        return gen.generateKey()
    }

    fun encrypt(plain: String): String {
        if (plain.isEmpty()) return ""
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val out = c.iv + c.doFinal(plain.toByteArray(Charsets.UTF_8))
        return PREFIX + Base64.encodeToString(out, Base64.NO_WRAP)
    }

    /** Values written before encryption existed are returned as they are (and encrypted on the next write). */
    fun decrypt(stored: String?): String {
        if (stored.isNullOrEmpty()) return ""
        if (!stored.startsWith(PREFIX)) return stored
        return try {
            val b = Base64.decode(stored.removePrefix(PREFIX), Base64.NO_WRAP)
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, b, 0, 12))
            String(c.doFinal(b, 12, b.size - 12), Charsets.UTF_8)
        } catch (e: Exception) {
            ""            // key gone (e.g. app data restored elsewhere): the value is unreadable by design
        }
    }

    /** Passphrase of the encrypted database: 32 random bytes as hex, stored only in encrypted form. */
    fun databasePassphrase(context: Context): String {
        val p = context.getSharedPreferences("epiprot_vault", Context.MODE_PRIVATE)
        decrypt(p.getString("db", null)).takeIf { it.length == 64 }?.let { return it }
        val hex = ByteArray(32).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        p.edit().putString("db", encrypt(hex)).commit()
        return hex
    }
}
