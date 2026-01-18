#include "kernel/types.h"
#include "kernel/fs.h"
#include "kernel/stat.h"
#include "user/user.h"

// 辅助函数：提取文件名
char* fmt_name(char* path) {
    char* p;
    // 从字符串末尾向前找第一个 '/'
    // 修正点：这里必须是 p >= path，防止遗漏第一个字符
    for (p = path + strlen(path); p >= path && *p != '/'; p--)
        ;
    p++; // 移动到 '/' 之后的一个字符
    return p;
}

void find(char* path, char* target) {
    char buf[512];
    char* p;
    int fd;
    struct dirent de;
    struct stat st;

    // [修正 1] 注意括号优先级！ ((fd = open) < 0)
    if ((fd = open(path, 0)) < 0) {
        fprintf(2, "find: cannot open %s\n", path);
        return;
    }

    if (fstat(fd, &st) < 0) {
        fprintf(2, "find: cannot stat %s\n", path);
        close(fd);
        return;
    }

    switch (st.type) {
        // === 情况 A: 当前路径是文件 ===
        case T_FILE:
            // [修正 2] 显式判断 == 0 (相等)，并打印
            if (strcmp(fmt_name(path), target) == 0) {
                printf("%s\n", path);
            }
            break; // 记得 break，否则会继续执行 T_DIR

        // === 情况 B: 当前路径是目录 ===
        case T_DIR:
            if (strlen(path) + 1 + DIRSIZ + 1 > sizeof(buf)) {
                printf("find: path too long\n");
                break;
            }
            
            strcpy(buf, path);
            p = buf + strlen(buf);
            *p++ = '/';

            while (read(fd, &de, sizeof(de)) == sizeof(de)) {
                if (de.inum == 0)
                    continue;
                
                // 跳过 . 和 ..
                if (strcmp(de.name, ".") == 0 || strcmp(de.name, "..") == 0)
                    continue;

                memmove(p, de.name, DIRSIZ);
                p[DIRSIZ] = 0; // 确保字符串以 \0 结尾

                // 递归
                find(buf, target);
            }
            break;
    }
    close(fd);
}

int main(int argc, char* argv[]) {
    if (argc != 3) {
        fprintf(2, "Usage: find <path> <filename>\n");
        exit(1);
    }
    find(argv[1], argv[2]);
    exit(0);
}