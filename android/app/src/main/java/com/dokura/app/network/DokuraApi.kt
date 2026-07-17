package com.dokura.app.network

import com.dokura.app.data.CatalogResponse
import com.dokura.app.data.FileDetailDto
import com.dokura.app.data.IdentityResponse
import com.dokura.app.data.RatingBody
import com.dokura.app.data.RatingResponse
import com.dokura.app.data.TagCandidatesResponse
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import okhttp3.ResponseBody
import retrofit2.Response

interface DokuraApi {
    @GET("api/v1/identity")
    suspend fun identity(): Response<ResponseBody>

    @GET("api/v1/catalog")
    suspend fun catalog(
        @Query("path") path: String,
        @Query("page") page: Int,
        @Query("per_page") perPage: Int = 40,
        @Query("query") query: String,
        @Query("scope") scope: String,
        @Query("tag_id") tagIds: List<Long>,
        @Query("tag_mode") tagMode: String,
        @Query("rating_min") ratingMin: Int,
        @Query("rating_max") ratingMax: Int,
        @Query("sort") sort: String,
        @Query("direction") direction: String,
    ): CatalogResponse

    @GET("api/v1/tags")
    suspend fun tags(
        @Query("path") path: String,
        @Query("scope") scope: String,
    ): TagCandidatesResponse

    @GET("api/v1/files/{id}")
    suspend fun detail(@Path("id") id: String): FileDetailDto

    @PUT("api/v1/files/{id}/rating")
    suspend fun setRating(@Path("id") id: String, @Body rating: RatingBody): RatingResponse
}
