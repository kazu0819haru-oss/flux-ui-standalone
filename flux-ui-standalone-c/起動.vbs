Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' このファイルのあるフォルダを取得
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' パスにスペースが含まれても動くよう Chr(34) でクォートを組み立てる
q = Chr(34)
WshShell.CurrentDirectory = ScriptDir
WshShell.Run "cmd /c " & q & q & ScriptDir & "\起動.bat" & q & q, 0, False

WScript.Quit
