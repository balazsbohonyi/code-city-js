export function risky(a, b, c) {
  if (a) {
    if (b && c) {
      for (let i = 0; i < 3; i++) {
        if (i === 1) {
          return a + b + c + i;
        }
      }
    }
  }
  return 0;
}
