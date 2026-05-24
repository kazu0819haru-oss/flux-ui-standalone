Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' このファイルのあるフォルダを取得
ScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' 起動.bat を非表示で実行
WshShell.Run "cmd /c cd /d """ & ScriptDir & """ && 起動.bat", 0, False

WScript.Quit
