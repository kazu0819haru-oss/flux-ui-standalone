Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
q = Chr(34)
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(ScriptDir, fso.GetBaseName(WScript.ScriptFullName) & ".bat")
WshShell.CurrentDirectory = ScriptDir
WshShell.Run "cmd /c " & q & q & batPath & q & q, 0, False
WScript.Quit
