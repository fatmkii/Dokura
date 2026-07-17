package com.dokura.app

import android.content.pm.ActivityInfo
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import android.os.ParcelFileDescriptor
import org.junit.Rule
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MainActivityTest {
    @get:Rule val composeRule = createAndroidComposeRule<MainActivity>()

    @Before fun portrait() {
        composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        composeRule.waitForIdle()
    }

    @Test fun catalogRecentAndSettingsNavigationIsAvailable() {
        composeRule.onNodeWithText(UiText.SearchHint).assertIsDisplayed()
        composeRule.onNodeWithText(UiText.Recent).performClick()
        composeRule.onNodeWithText(UiText.EmptyRecent).assertIsDisplayed()
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("serverAddress").assertIsDisplayed()
    }

    @Test fun apiKeyIsMaskedAndThemeChangePreservesFormState() {
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("serverAddress").performTextInput("192.168.1.8")
        composeRule.onNodeWithTag("apiKey").performTextInput("never-show-this-key")
        composeRule.onNodeWithTag("choice:暗色").performScrollTo().performClick()
        composeRule.onNodeWithTag("serverAddress").assertTextContains("192.168.1.8")
        composeRule.onNodeWithTag("apiKey").assert(SemanticsMatcher.keyIsDefined(SemanticsProperties.Password))
    }

    @Test fun gridChoicesRemainAvailableAfterRotation() {
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("choice:5 列").performScrollTo().performClick()
        composeRule.onNodeWithText("• 5 列").assertIsDisplayed()
        composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        composeRule.waitUntil(5_000) {
            composeRule.onAllNodesWithText("• 5 列").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("• 5 列").assertExists()
        composeRule.onNodeWithText("4 列").assertExists()
        composeRule.onNodeWithText("6 列").assertExists()
    }

    @Test fun settingsRemainUsableAtTwoHundredPercentFontScale() {
        val original = composeRule.activity.resources.configuration.fontScale
        try {
            shell("settings put system font_scale 2.0")
            composeRule.activityRule.scenario.recreate()
            composeRule.waitUntil(5_000) { composeRule.activity.resources.configuration.fontScale >= 1.9f }
            composeRule.onNodeWithText(UiText.Settings).performClick()
            composeRule.onNodeWithTag("serverAddress").assertIsDisplayed()
            composeRule.onNodeWithTag("choice:6 列").performScrollTo().assertIsDisplayed()
        } finally {
            shell("settings put system font_scale $original")
            composeRule.activityRule.scenario.recreate()
        }
    }

    private fun shell(command: String) {
        val descriptor = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command)
        ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { it.readBytes() }
    }
}
