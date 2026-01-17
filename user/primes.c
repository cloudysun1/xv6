#include "kernel/types.h"
#include "user/user.h"

void sieve(int* p_left) {
    close(p_left[1]);

    int prime;

    if (read(p_left[0], &prime, 4) == 0) {
        exit(0);
    }
    printf("prime %d\n", prime);

    int p_right[2];
    pipe(p_right);

    if (fork() == 0) {
        close(p_left[0]);
        sieve(p_right);
    } else {
        close(p_right[0]);
        int n;
        while (read(p_left[0], &n, 4)) {
            if (n % prime != 0) {
                write(p_right[1], &n, 4);
            }
        }
    }
    close(p_left[0]);
    close(p_right[1]);
    wait(0);
    exit(0);
}

int main() {
    int p[2];
    pipe(p);

    if (fork() == 0) {
        sieve(p);
    } else {
        close(p[0]);
        for (int i = 2; i <= 35; i++) {
            write(p[1], &i, 4);
        }
        close(p[1]);
        wait(0);
    }

    exit(0);
}