package com.dokura.app.data

import com.google.gson.annotations.SerializedName

data class ConnectionSettings(
    val address: String = "",
    val port: Int = 8000,
)

enum class ThemeMode { SYSTEM, LIGHT, DARK }
enum class ReadingDirection { LEFT_TO_RIGHT, RIGHT_TO_LEFT }

data class AppSettings(
    val connection: ConnectionSettings = ConnectionSettings(),
    val theme: ThemeMode = ThemeMode.SYSTEM,
    val previewColumns: Int = 4,
    val coverWidthPercent: Int = 30,
    val readingDirection: ReadingDirection = ReadingDirection.LEFT_TO_RIGHT,
    val keepScreenOn: Boolean = false,
    val cacheLimitGb: Int = 5,
)

data class IdentityResponse(
    val service: String,
    @SerializedName("server_version") val serverVersion: String,
    @SerializedName("api_version") val apiVersion: String,
)

data class TagDto(val id: Long, val category: String, val value: String)
data class TagCandidateDto(
    val id: Long,
    val category: String,
    val value: String,
    @SerializedName("uses") val count: Int,
)
data class TagCandidatesResponse(val items: List<TagCandidateDto>)

data class CatalogItemDto(
    val kind: String,
    val id: String? = null,
    val name: String,
    @SerializedName("relative_path") val relativePath: String,
    val size: Long = 0,
    @SerializedName("modified_ns") val modifiedNs: Long = 0,
    val rating: Int = 0,
    val status: String = "ready",
    @SerializedName("cover_status") val coverStatus: String = "not_generated",
    @SerializedName("content_version") val contentVersion: String = "",
    @SerializedName("tags") private val serializedTags: List<TagDto>? = null,
) {
    val tags: List<TagDto> get() = serializedTags.orEmpty()
}

data class CatalogResponse(
    val items: List<CatalogItemDto>,
    val page: Int,
    @SerializedName("per_page") val perPage: Int,
    val total: Int,
    val pages: Int,
    @SerializedName("result_version") val resultVersion: String,
)

data class PageDto(
    val number: Int,
    val unavailable: Boolean,
    @SerializedName("unavailable_reason") val unavailableReason: String? = null,
)

data class FileDetailDto(
    val id: String,
    val name: String,
    @SerializedName("relative_path") val relativePath: String,
    val size: Long,
    @SerializedName("modified_ns") val modifiedNs: Long,
    val rating: Int,
    val status: String,
    @SerializedName("cover_status") val coverStatus: String,
    @SerializedName("content_version") val contentVersion: String,
    val tags: List<TagDto> = emptyList(),
    @SerializedName("unclassified_tags") val unclassifiedTags: List<String> = emptyList(),
    @SerializedName("page_count") val pageCount: Int,
    @SerializedName("unavailable_page_count") val unavailablePageCount: Int,
    val pages: List<PageDto> = emptyList(),
    @SerializedName("last_error") val lastError: String? = null,
)

data class RatingBody(val rating: Int)
data class RatingResponse(val id: String, val rating: Int, @SerializedName("updated_at") val updatedAt: String?)

data class CatalogQuery(
    val path: String = "",
    val search: String = "",
    val recursive: Boolean = false,
    val tagIds: List<Long> = emptyList(),
    val tagMode: String = "grouped",
    val ratingMin: Int = 0,
    val ratingMax: Int = 5,
    val sort: String = "name",
    val direction: String = "asc",
)
