/* Optimized native CPU baseline: the same three strategies as streaming loops over int32 cents.
 * Usage: baseline PRICES.bin STRATEGY REPS    (STRATEGY: sma | trend | meanrev)
 * Prints: ns_per_bar trades checksum
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct { int64_t cash, shares, trades; } Book;

static inline void trade(Book *b, int32_t price, int buy) {
    if (buy) { b->cash -= (int64_t)price * 10; b->shares += 10; }
    else     { b->cash += (int64_t)price * 10; b->shares -= 10; }
    b->trades++;
}

static void run_sma(const int32_t *p, size_t n, Book *b) {
    int64_t s10 = 0, s30 = 0;
    for (size_t i = 0; i < n; i++) {
        s10 += p[i]; if (i >= 10) s10 -= p[i - 10];
        s30 += p[i]; if (i >= 30) s30 -= p[i - 30];
        if (i < 29) continue;
        trade(b, p[i], (s10 / 10) > (s30 / 30));
    }
}

static void run_trend(const int32_t *p, size_t n, Book *b) {
    int64_t s12 = 0, s26 = 0;
    for (size_t i = 0; i < n; i++) {
        s12 += p[i]; if (i >= 12) s12 -= p[i - 12];
        s26 += p[i]; if (i >= 26) s26 -= p[i - 26];
        if (i < 25) continue;
        int64_t fast = s12 / 12, slow = s26 / 26;
        if (fast > slow) { if (p[i] > fast) trade(b, p[i], 1); }
        else if (p[i] < slow) trade(b, p[i], 0);
    }
}

static void run_meanrev(const int32_t *p, size_t n, Book *b) {
    double s = 0, ss = 0;
    for (size_t i = 0; i < n; i++) {
        s += p[i]; ss += (double)p[i] * p[i];
        if (i >= 20) { s -= p[i - 20]; ss -= (double)p[i - 20] * p[i - 20]; }
        if (i < 19) continue;
        double mean = s / 20, var = ss / 20 - mean * mean;
        double sd = sqrt(var > 0 ? var : 0);
        if (p[i] <= mean - 2 * sd) trade(b, p[i], 1);
        else if (p[i] >= mean + 2 * sd) trade(b, p[i], 0);
    }
}

int main(int argc, char **argv) {
    if (argc != 4) { fprintf(stderr, "usage: %s PRICES.bin sma|trend|meanrev REPS\n", argv[0]); return 2; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END); size_t n = (size_t)ftell(f) / 4; fseek(f, 0, SEEK_SET);
    int32_t *p = malloc(n * 4);
    if (fread(p, 4, n, f) != n) { fprintf(stderr, "short read\n"); return 1; }
    fclose(f);
    void (*fn)(const int32_t *, size_t, Book *) =
        !strcmp(argv[2], "sma") ? run_sma : !strcmp(argv[2], "trend") ? run_trend : run_meanrev;
    long reps = atol(argv[3]);
    Book b = {0};
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (long r = 0; r < reps; r++) fn(p, n, &b);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double ns = (t1.tv_sec - t0.tv_sec) * 1e9 + (t1.tv_nsec - t0.tv_nsec);
    printf("%.4f %lld %lld\n", ns / ((double)n * reps), (long long)(b.trades / reps), (long long)(b.cash + b.shares));
    return 0;
}
