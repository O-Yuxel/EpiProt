package org.epiprot.watch

import android.app.Application
import android.content.Context
import org.epiprot.watch.feedback.Notifications

class EpiProtApp : Application() {
    val controller: WatchController by lazy { WatchController(this) }

    override fun onCreate() {
        super.onCreate()
        Notifications.createChannels(this)
    }

    companion object {
        fun controller(context: Context): WatchController =
            (context.applicationContext as EpiProtApp).controller
    }
}
