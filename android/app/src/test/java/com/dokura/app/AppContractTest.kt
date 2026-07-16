package com.dokura.app

import org.junit.Assert.assertEquals
import org.junit.Test

class AppContractTest {
    @Test
    fun apiVersionIsV1() {
        assertEquals("1", AppContract.ApiVersion)
    }
}
