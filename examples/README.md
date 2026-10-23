# Earlier standalone viewers

For the direct browser viewer, open `browser/fuse-camera-viewer.html` and enter the printer address. Browser network restrictions may require serving the file over local HTTP.

For the Node helper, run `node examples/node/fuse-camera-live.cjs` with Node.js 22 or newer and open `http://localhost:8766/`. Enter your printer host in the page.

Both examples use an earlier reply-paced refresh model. They are retained as examples and may stall if the printer drops a refresh. The Python relay is the recommended implementation.
