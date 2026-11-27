# Replays one recorded deliberation (no API key, no LLM call).
# Rendered by showcase/make_showcase.sh — do not edit the outputs by hand.
Output showcase/demo.gif
Output showcase/demo.mp4

Require panel

Set Shell "bash"
Set FontSize 15
Set Width 1280
Set Height 880
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 12

Hide
Type "export COLUMNS=118 PS1='$ '; clear"
Enter
Show

Type "panel demo $DEMO_TRACE --pause 3.5"
Sleep 400ms
Enter
Sleep 22s
Sleep 6s
