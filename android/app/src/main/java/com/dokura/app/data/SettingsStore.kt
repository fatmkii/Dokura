package com.dokura.app.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.settingsDataStore by preferencesDataStore("settings")

class SettingsStore(private val context: Context) {
    private object Keys {
        val address = stringPreferencesKey("server_address")
        val port = intPreferencesKey("server_port")
        val theme = stringPreferencesKey("theme")
        val columns = intPreferencesKey("preview_columns")
        val coverWidth = intPreferencesKey("cover_width_percent")
        val readingDirection = stringPreferencesKey("reading_direction")
        val keepScreenOn = booleanPreferencesKey("keep_screen_on")
        val cacheLimitGb = intPreferencesKey("cache_limit_gb")
    }

    val settings: Flow<AppSettings> = context.settingsDataStore.data.map { values ->
        AppSettings(
            connection = ConnectionSettings(values[Keys.address].orEmpty(), values[Keys.port] ?: 8000),
            theme = runCatching { ThemeMode.valueOf(values[Keys.theme] ?: "SYSTEM") }.getOrDefault(ThemeMode.SYSTEM),
            previewColumns = values[Keys.columns]?.takeIf { it in setOf(4, 5, 6) } ?: 4,
            coverWidthPercent = values[Keys.coverWidth]?.takeIf { it in setOf(20, 30, 40) } ?: 30,
            readingDirection = runCatching {
                ReadingDirection.valueOf(values[Keys.readingDirection] ?: "LEFT_TO_RIGHT")
            }.getOrDefault(ReadingDirection.LEFT_TO_RIGHT),
            keepScreenOn = values[Keys.keepScreenOn] ?: false,
            cacheLimitGb = values[Keys.cacheLimitGb]?.takeIf { it in setOf(1, 5, 10, 20) } ?: 5,
        )
    }

    suspend fun saveConnection(value: ConnectionSettings) = context.settingsDataStore.edit {
        it[Keys.address] = value.address.trim()
        it[Keys.port] = value.port
    }

    suspend fun setTheme(value: ThemeMode) = context.settingsDataStore.edit { it[Keys.theme] = value.name }
    suspend fun setColumns(value: Int) = context.settingsDataStore.edit { it[Keys.columns] = value }
    suspend fun setCoverWidth(value: Int) = context.settingsDataStore.edit { it[Keys.coverWidth] = value }
    suspend fun setReadingDirection(value: ReadingDirection) = context.settingsDataStore.edit { it[Keys.readingDirection] = value.name }
    suspend fun setKeepScreenOn(value: Boolean) = context.settingsDataStore.edit { it[Keys.keepScreenOn] = value }
    suspend fun setCacheLimitGb(value: Int) = context.settingsDataStore.edit { it[Keys.cacheLimitGb] = value }
}
