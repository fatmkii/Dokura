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
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeLeft
import androidx.compose.ui.test.click
import com.dokura.app.data.ReadingDirection
import com.dokura.app.reader.ReaderAction
import com.dokura.app.ui.readerPageGestures
import org.junit.Rule
import org.junit.Before
import org.junit.Test
import org.junit.Assert.assertEquals
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

    @Test fun stageSevenReadingAndCacheSettingsPersistAcrossRotation() {
        composeRule.onNodeWithText(UiText.Settings).performClick()
        composeRule.onNodeWithTag("choice:${UiText.RightToLeft}").performScrollTo().performClick()
        composeRule.onNodeWithTag("keepScreenOn").performScrollTo().performClick()
        composeRule.onNodeWithTag("choice:10 GB").performScrollTo().performClick()
        composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
        composeRule.waitUntil(5_000) {
            composeRule.onAllNodesWithText("• ${UiText.RightToLeft}").fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("• ${UiText.RightToLeft}").assertExists()
        composeRule.onNodeWithText("• 10 GB").assertExists()
    }

    @Test fun readerGestureLayerUsesDirectionAndBlocksZoomedDragButKeepsEdgeTap() {
        var action by mutableStateOf(ReaderAction.NONE)
        var direction by mutableStateOf(ReadingDirection.LEFT_TO_RIGHT)
        var zoom by mutableStateOf(1f)
        composeRule.activity.setContent {
            Box(
                Modifier.fillMaxSize().testTag("gestureLayer")
                    .readerPageGestures(1, direction, zoom, { action = it }),
            ) { Text(action.name) }
        }
        composeRule.onNodeWithTag("gestureLayer").performTouchInput { swipeLeft() }
        composeRule.runOnIdle { assertEquals(ReaderAction.NEXT, action) }

        composeRule.runOnIdle { action = ReaderAction.NONE; zoom = 2f }
        composeRule.onNodeWithTag("gestureLayer").performTouchInput { swipeLeft() }
        composeRule.runOnIdle { assertEquals(ReaderAction.NONE, action) }

        composeRule.onNodeWithTag("gestureLayer").performTouchInput { click(centerRight) }
        composeRule.waitUntil(1_000) { action == ReaderAction.NEXT }
        composeRule.runOnIdle { assertEquals(ReaderAction.NEXT, action) }

        composeRule.runOnIdle { action = ReaderAction.NONE; direction = ReadingDirection.RIGHT_TO_LEFT }
        composeRule.onNodeWithTag("gestureLayer").performTouchInput { click(centerLeft) }
        composeRule.waitUntil(1_000) { action == ReaderAction.NEXT }
        composeRule.runOnIdle { assertEquals(ReaderAction.NEXT, action) }
    }

    private fun shell(command: String) {
        val descriptor = InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command)
        ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { it.readBytes() }
    }
}
