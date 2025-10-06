// no-op polyfills for jsdom
if (!Element.prototype.hasPointerCapture) {
  // @ts-ignore jsdom lacks this API
  Element.prototype.hasPointerCapture = () => false;
}

if (!Element.prototype.releasePointerCapture) {
  // @ts-ignore jsdom lacks this API
  Element.prototype.releasePointerCapture = () => {};
}
