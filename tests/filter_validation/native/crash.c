/*
 * 用于 test_process_crash.py 的 hard_crash 场景。
 *
 * 通过写 NULL 触发一次真实的 access violation，让 Windows kernel 以
 * STATUS_ACCESS_VIOLATION (0xC0000005) 终止进程。
 *
 * 用 tcc 编译成 crash.exe（约 2KB）：
 *     tcc.exe crash.c -o crash.exe
 *
 * 之所以不能在 Python 里直接触发 AV：
 *   Python 3.13 的 ctypes 层给几乎所有原生调用装了 SEH handler，
 *   AV 会被拦成 OSError，最终 exit code = 1，无法测试真实崩溃路径。
 */
int main(void) {
    /* volatile 防止编译器优化掉这次写入 */
    *(volatile int *)0 = 0;
    return 0;
}
