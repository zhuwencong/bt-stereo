@echo off
rem 转发到「启动.bat」。两个入口内容相同容易改漏，
rem 所以只保留中文名那版做实现，这个仅作英文名入口。
call "%~dp0启动.bat" %*
