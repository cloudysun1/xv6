#include "kernel/types.h"
#include "user/user.h"

int main(int argc, char *argv[]) {
  int p2c[2];
  int c2p[2];

  char buf[1] = {'A'};

  if (pipe(p2c) < 0 || pipe(c2p) < 0) {
    fprintf(2, "pipe error\n");
    exit(1);
  }

  int pid = fork();

  if (pid < 0) {
    fprintf(2, "fork error\n");
    exit(1);
  }

  if (pid == 0) {

    close(p2c[1]);
    close(c2p[0]);


    if (read(p2c[0], buf, sizeof(buf)) < 0) {
      fprintf(2,"read error\n");
    }

    fprintf(1, "%d: received ping\n", getpid());
    write(c2p[1], buf, sizeof(buf));

    exit(0);

  } else {
    close(p2c[0]);
    close(c2p[1]);
    write(p2c[1], buf, sizeof(buf));

    
    if (read(c2p[0], buf, sizeof(buf)) < 0) {
      fprintf(2,"read error\n");
    }

    fprintf(1, "%d: received pong\n", getpid());

    exit(0);
  }
}