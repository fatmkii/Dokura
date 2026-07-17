package com.dokura.app.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Index
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "reading_progress")
data class ReadingProgress(
    @PrimaryKey val fileId: String,
    val page: Int,
    val lastReadAt: Long,
    val fileName: String,
    val relativePath: String,
    val progressUpdatedAt: Long = lastReadAt,
)

@Dao
interface ReadingProgressDao {
    @Query("SELECT * FROM reading_progress WHERE lastReadAt > 0 ORDER BY lastReadAt DESC LIMIT 100")
    fun recent(): Flow<List<ReadingProgress>>

    @Query("SELECT * FROM reading_progress WHERE fileId = :fileId")
    suspend fun get(fileId: String): ReadingProgress?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(progress: ReadingProgress)

    @Query("DELETE FROM reading_progress WHERE fileId = :fileId")
    suspend fun delete(fileId: String)

    @Query("UPDATE reading_progress SET lastReadAt = 0 WHERE fileId IN (SELECT fileId FROM reading_progress WHERE lastReadAt > 0 ORDER BY lastReadAt DESC LIMIT -1 OFFSET 100)")
    suspend fun trimRecent()
}

enum class CacheCategory { TEMP, PREVIEW, ORIGINAL, COVER }

@Entity(
    tableName = "cache_entries",
    indices = [Index(value = ["category", "lastAccessAt"])],
)
data class CacheEntry(
    @PrimaryKey val key: String,
    val category: CacheCategory,
    val relativePath: String,
    val bytes: Long,
    val contentVersion: String,
    val lastAccessAt: Long,
)

@Dao
interface CacheDao {
    @Query("SELECT * FROM cache_entries WHERE `key` = :key")
    suspend fun get(key: String): CacheEntry?

    @Query("SELECT * FROM cache_entries ORDER BY category, lastAccessAt")
    suspend fun all(): List<CacheEntry>

    @Query("SELECT * FROM cache_entries WHERE category = :category ORDER BY lastAccessAt")
    suspend fun oldest(category: CacheCategory): List<CacheEntry>

    @Query("SELECT COALESCE(SUM(bytes), 0) FROM cache_entries")
    fun totalBytes(): Flow<Long>

    @Query("SELECT COALESCE(SUM(bytes), 0) FROM cache_entries")
    suspend fun totalBytesNow(): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: CacheEntry)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entries: List<CacheEntry>)

    @Query("DELETE FROM cache_entries WHERE `key` = :key")
    suspend fun delete(key: String)

    @Query("DELETE FROM cache_entries")
    suspend fun deleteAll()
}

@Database(entities = [ReadingProgress::class, CacheEntry::class], version = 3, exportSchema = true)
abstract class DokuraDatabase : RoomDatabase() {
    abstract fun readingProgress(): ReadingProgressDao
    abstract fun cache(): CacheDao

    companion object {
        @Volatile private var instance: DokuraDatabase? = null
        private val migration1To2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS `cache_entries` (`key` TEXT NOT NULL, `category` TEXT NOT NULL, `relativePath` TEXT NOT NULL, `bytes` INTEGER NOT NULL, `contentVersion` TEXT NOT NULL, `lastAccessAt` INTEGER NOT NULL, PRIMARY KEY(`key`))")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_cache_entries_category_lastAccessAt` ON `cache_entries` (`category`, `lastAccessAt`)")
            }
        }
        private val migration2To3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE `reading_progress` ADD COLUMN `progressUpdatedAt` INTEGER NOT NULL DEFAULT 0")
                db.execSQL("UPDATE `reading_progress` SET `progressUpdatedAt` = `lastReadAt`")
            }
        }

        fun create(context: Context): DokuraDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(context.applicationContext, DokuraDatabase::class.java, "dokura.db")
                .addMigrations(migration1To2, migration2To3)
                .build()
                .also { instance = it }
        }
    }
}
