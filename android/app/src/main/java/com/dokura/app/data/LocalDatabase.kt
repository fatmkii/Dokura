package com.dokura.app.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
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
)

@Dao
interface ReadingProgressDao {
    @Query("SELECT * FROM reading_progress ORDER BY lastReadAt DESC LIMIT 100")
    fun recent(): Flow<List<ReadingProgress>>

    @Query("SELECT * FROM reading_progress WHERE fileId = :fileId")
    suspend fun get(fileId: String): ReadingProgress?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(progress: ReadingProgress)

    @Query("DELETE FROM reading_progress WHERE fileId = :fileId")
    suspend fun delete(fileId: String)
}

@Database(entities = [ReadingProgress::class], version = 1, exportSchema = true)
abstract class DokuraDatabase : RoomDatabase() {
    abstract fun readingProgress(): ReadingProgressDao

    companion object {
        fun create(context: Context): DokuraDatabase = Room.databaseBuilder(
            context,
            DokuraDatabase::class.java,
            "dokura.db",
        ).build()
    }
}
