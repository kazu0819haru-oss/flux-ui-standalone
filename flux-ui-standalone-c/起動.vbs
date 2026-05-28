Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
q = Chr(34)
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(ScriptDir, fso.GetBaseName(WScript.ScriptFullName) & ".bat")
splashPath = fso.BuildPath(ScriptDir, "splash.html")

' Read Flask port from config.json (default: 5000)
flaskPort = 5000
configPath = fso.BuildPath(ScriptDir, "config.json")
If fso.FileExists(configPath) Then
    Dim ts: Set ts = fso.OpenTextFile(configPath, 1)
    Dim txt: txt = ts.ReadAll()
    ts.Close
    Dim re: Set re = CreateObject("VBScript.RegExp")
    re.Pattern = """flask_port""\s*:\s*(\d+)"
    Dim m: Set m = re.Execute(txt)
    If m.Count > 0 Then flaskPort = CInt(m(0).SubMatches(0))
End If

' Open splash page immediately in default browser
WshShell.Run "cmd /c start """" " & q & "file:///" & Replace(splashPath, "\", "/") & "?port=" & flaskPort & q, 0, False

' Launch bat silently
WshShell.CurrentDirectory = ScriptDir
WshShell.Run "cmd /c " & q & q & batPath & q & q, 0, False
WScript.Quit
