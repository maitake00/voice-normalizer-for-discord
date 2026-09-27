==============================================================
  Voice Normalizer for Discord  (test version v{version})
  README
==============================================================

* What is this?
  In Discord calls, some people are much louder or quieter than others.
  This tool evens them out automatically by adjusting Discord's own
  per-user volume (the slider you get when you right-click someone).

  - Call audio is never recorded, saved, or sent anywhere.
    The tool only measures loudness on your PC.
  - Only what YOU hear changes. Other people's settings, and how they
    hear you, are not affected.
  - This is not an official Discord product. Use at your own risk.


* Download
  Get the latest version, source code, and report problems here:
    {repo_url}
  To avoid tampered copies, please download it only from this page.


* Requirements
  - Windows 11 recommended
    (Windows 10 usually works if it is up to date. If your PC can't
     capture Discord's audio alone, the app shows "Measuring all PC
     audio". In that case, stop games and music while testing.)
  - The Discord desktop app (the browser version is not supported)


* Starting the app
  1. Extract (unzip) this zip file anywhere.
     Do not run the app from inside the zip.
  2. Double-click VoiceNormalizerForDiscord.exe

  If a blue "Windows protected your PC" screen appears:
    This happens because the app is not code-signed.
    Click [More info] -> [Run anyway].


* Before you start (one time)
  On first launch, the app asks how you want to use it. Pick one:

  A. "I was invited as a tester"
     For people who are Discord friends with the person who shared this
     tool.
     1. Send them your Discord username and ask to be added as a tester.
     2. An invitation arrives at the email address of your Discord
        account. Open it and accept it. (Check your spam folder if it
        doesn't arrive.)
     3. Start the app, choose "I was invited as a tester", and click
        [Start].
     4. Discord shows a confirmation prompt. Click [Authorize].
        (If the Discord window is behind other windows, the prompt is
         easy to miss.)

  B. "Use my own Discord application"
     For everyone else. No friend request or invitation needed.
     1. Start the app, choose "Use my own Discord application", and
        click [Set up].
     2. Follow the on-screen guide (1-2 minutes, free). It shows exactly
        which buttons to click in the Discord Developer Portal.
     3. Discord shows a confirmation prompt. Click [Authorize].

  You can switch between A and B later in [Settings].


* How to use
  Keep the app open and use Discord voice calls as usual.

  - When a member speaks alone, their card goes from
    "Learning their voice..." -> "Turning up/down gradually"
    -> "Volume is just right"
  - The card of whoever is speaking gets a green border
  - Your own voice is not adjusted (nothing happens if you are alone)
  - Nothing is measured while two or more people talk at once
  - [Settings] lets you change "Target volume" and "Balancing"
  - The app follows your Windows display language (English or Japanese).
    You can switch it under "Language" in [Settings].

  Recommended: in Discord, set User Settings -> Voice & Video ->
  Attenuation to 0%. Otherwise volumes can't be measured correctly.


* What we'd like you to check
  1. Do "Receiving audio" and "Voices detected" turn green at the top?
  2. Do member cards move past "Learning their voice..." and does the
     volume (%) change?
  3. After talking for a while, do voices sound more even?
     (Also tell us if it's too loud/quiet overall, or too slow/fast.)


* How to send results
  Click [Copy log] at the bottom right of the app, paste it into a
  message, and send it together with your impressions.
  A screenshot of the app also helps a lot.
  If you have a GitHub account, you can also post it under "Issues"
  on the page above.

  Note: the log contains the Discord names of members in the call.
  Feel free to remove them before sending.


* Stopping / uninstalling
  - Closing the app stops it.
    Volumes it changed stay as they are in Discord. To reset someone,
    right-click them in Discord and set the volume back to 100%.
  - To uninstall, delete the extracted folder and this folder
    (it contains your Client ID and other settings):
      %APPDATA%\VoiceNormalizerForDiscord
    Tip: paste the line above into the File Explorer address bar.
  - If you created your own Discord application, you can delete it in
    the Developer Portal.
