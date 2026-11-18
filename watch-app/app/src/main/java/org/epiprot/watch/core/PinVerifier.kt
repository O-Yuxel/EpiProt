package org.epiprot.watch.core

import java.security.MessageDigest

/**
 * Checks the 4-digit PIN on the watch. Only a salted SHA-256 hash is stored; the phone app sends it.
 * Until the phone has sent a PIN, the demo PIN 1234 is used.
 */
class PinVerifier(val salt: String, private val hash: String) {

    fun verify(pin: String): Boolean {
        if (pin.length != PIN_LENGTH || !pin.all { it in '0'..'9' }) return false
        return MessageDigest.isEqual(hashPin(pin, salt).toByteArray(), hash.toByteArray())
    }

    val isDemo: Boolean get() = salt == DEMO_SALT

    companion object {
        const val PIN_LENGTH = 4
        private const val DEMO_SALT = "epiprot-demo"

        fun hashPin(pin: String, salt: String): String =
            MessageDigest.getInstance("SHA-256").digest((salt + pin).toByteArray())
                .joinToString("") { "%02x".format(it) }

        fun demo() = PinVerifier(DEMO_SALT, hashPin("1234", DEMO_SALT))
    }
}
