// Read-only live smoke test. Requires a headless Chromium browser on port 9223.
const assert = require('node:assert/strict');
(async () => {
    const tabs = await (await fetch('http://127.0.0.1:9223/json')).json();
    const ws = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
    await new Promise(resolve => ws.addEventListener('open', resolve, { once: true }));
    let seq = 0;
    const pending = new Map();
    ws.addEventListener('message', event => {
        const message = JSON.parse(event.data);
        if (pending.has(message.id)) {
            const { resolve, reject } = pending.get(message.id);
            pending.delete(message.id);
            message.error ? reject(message.error) : resolve(message.result);
        }
    });
    const send = (method, params = {}) => new Promise((resolve, reject) => {
        const id = ++seq; pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async expression => {
        const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
        if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
        return result.result.value;
    };
    try {
        await send('Page.navigate', { url: 'http://127.0.0.1:5000/warehouse-borrow-log/new-multiple' });
        let ready;
        for (let i = 0; i < 100; i++) {
            ready = await evaluate('document.querySelector(".row-number")?.textContent === "1"');
            if (ready) break;
            await new Promise(resolve => setTimeout(resolve, 200));
        }
        if (!ready) console.log(await evaluate('({url:location.href,state:document.readyState,text:document.body.innerText.slice(0,400),lookup:typeof window.attachBorrowLookup})'));
        assert.ok(ready, 'grid initialized');
        const report = await evaluate(String.raw`(async () => {
            const body = document.getElementById('batch-rows');
            const field = (row, name) => body.rows[row].querySelector('[name="' + name + '"]');
            field(0, 'borrower').value = 'Browser check';
            field(0, 'purpose').value = 'Testing';
            const noCopyButton = !document.getElementById('copy-details');
            field(4, 'purpose').value = 'Testing';
            document.getElementById('add-row').click();
            const added = body.rows.length === 6 && field(5, 'purpose').value === 'Testing';
            body.rows[5].querySelector('.remove-row').click();
            const removed = body.rows.length === 5;
            const clipboard = new DataTransfer();
            clipboard.setData('text/plain', 'Q1600095\t\nQ2500698\t');
            field(0, 'serial_number').dispatchEvent(new ClipboardEvent('paste', {clipboardData:clipboard,bubbles:true,cancelable:true}));
            for (let i=0; i<100; i++) {
                if (field(0,'item_number').value && field(1,'item_number').value) break;
                await new Promise(resolve => setTimeout(resolve,100));
            }
            return {noCopyButton,added,removed,serials:[field(0,'serial_number').value,field(1,'serial_number').value],items:[field(0,'item_number').value,field(1,'item_number').value]};
        })()`);
        console.log(report);
        assert.ok(report.noCopyButton && report.added && report.removed);
        assert.deepEqual(report.serials, ['Q1600095', 'Q2500698']);
        assert.deepEqual(report.items, ['NRU-161V-AWP', 'mPCIe-M2E']);
        const screenshot = await send('Page.captureScreenshot', {format:'png'});
        const file = require('node:path').join(process.env.TEMP, 'borrow-batch-preview.png');
        require('node:fs').writeFileSync(file, Buffer.from(screenshot.data, 'base64'));
        console.log('Live grid checks passed. No records submitted. Screenshot:', file);
    } finally {
        await send('Browser.close'); ws.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
