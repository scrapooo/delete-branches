# Delete Branches

批量删除 Git 本地/远程分支的交互式脚本。

## 环境要求

- Git
- Python 3.6+

## 使用方式

```powershell
# 交互式多选（推荐）
.\Delete-Branches.ps1
```

## 脚本会做什么

确认删除后，脚本依次执行以下操作：

1. `git fetch <remote>` —— 拉取最新远程信息
2. 检查本地和远程是否存在该分支
3. 要求输入 `y` 二次确认
4. 记录分支名和当前目录的 commit-id 到 `delete-branches.log`
5. `git branch -D <name>` —— 删除本地分支（强制删除，未合并也会删）
6. `git push <remote> --delete <name>` —— 删除远程分支

## 注意事项

- 当前分支不会被列出，避免误删
- 若想恢复被删除的分支可以在脚本目录下找到 `delete-branches.log`，使用其中的 commit-id 创建新分支
