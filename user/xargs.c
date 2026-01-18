#include "kernel/types.h"
#include "kernel/stat.h"
#include "user/user.h"
#include "kernel/param.h"

int main(int argc, char *argv[]) {
    char buf[1024];
    char *xargv[MAXARG];
    int xargc = 0;

    // 1. Copy command line arguments (skipping "xargs")
    // e.g., "xargs echo bye" -> xargv becomes ["echo", "bye"]
    for(int i = 1; i < argc; i++) {
        xargv[xargc] = argv[i];
        xargc++;
    }
    
    // Save the "base" index. We reset to this after every line.
    int base_argc = xargc;

    char c;
    int buf_idx = 0; // Index for writing into buf
    char *arg_start = buf; // Pointer to start of current argument

    // 2. Read stdin byte by byte
    while(read(0, &c, 1) > 0) {
        if(c == ' ' || c == '\n') {
            // End of a word
            buf[buf_idx++] = 0; // Null terminate the string in buffer
            
            // Add the string to arguments
            xargv[xargc++] = arg_start;
            
            // Update arg_start to point to the NEXT character slot
            arg_start = &buf[buf_idx];

            // If it was a newline, EXECUTE
            if(c == '\n') {
                xargv[xargc] = 0; // Null terminate the array for exec

                if(fork() == 0) {
                    exec(xargv[0], xargv);
                    exit(1);
                } else {
                    wait(0);
                }
                
                // RESET for next line
                xargc = base_argc; 
                // Note: You can reuse 'buf' from the beginning 
                // or keep writing forward. Reusing is safer for memory 
                // but requires logic reset. Simple way: keep writing forward 
                // until buffer full (unlikely in test) or just reset pointers.
                // For this lab, usually resetting buffer index to 0 is fine 
                // ONLY IF you process one line at a time completely.
                buf_idx = 0; 
                arg_start = buf;
            }
        } else {
            // Normal character
            buf[buf_idx++] = c;
        }
    }
    exit(0);
}