/* Standalone consecutive serial generator. No invoice, row selection or database calls. */
((root) => {
    const validateSerial = value => {
        if (typeof value !== 'string' || value.length > 255 || /[\r\n\t]/.test(value)) {
            throw Error('Enter one serial number of at most 255 characters.');
        }
        value = value.trim();
        if (!value || ['NA', 'NAN'].includes(value.toUpperCase()) || value.startsWith('=')) {
            throw Error('Enter an actual serial number, not a blank, placeholder or formula.');
        }
        return value;
    };
    const sequence = (first, count) => {
        first = validateSerial(first);
        count = Number(count);
        if (!Number.isInteger(count) || count < 1 || count > 20000) throw Error('Quantity must be from 1 to 20,000.');
        const match = /^(.*?)([0-9]+)$/.exec(first);
        if (!match) throw Error('The first serial must end with digits.');
        const [, prefix, digits] = match, start = BigInt(digits);
        const last = start + BigInt(count - 1);
        if (last.toString().length > digits.length) throw Error('This sequence changes the numeric width. Enter a smaller quantity.');
        return Array.from({length: count}, (_, index) => prefix + (start + BigInt(index)).toString().padStart(digits.length, '0'));
    };
    const attach = ({host, clipboard = root.navigator?.clipboard}) => {
        const find = id => host.querySelector(`#${id}`);
        const first = find('sequence-first'), count = find('sequence-count');
        const result = find('sequence-result'), summary = find('sequence-summary');
        const output = find('sequence-output'), copy = find('sequence-copy'), status = find('serial-status');
        const message = (text, error = false) => {
            status.textContent = text;
            status.classList.toggle('serial-error', error);
        };
        const invalidate = () => {
            result.hidden = true; output.value = ''; copy.disabled = true;
            message('Enter the first serial and quantity, then generate. No invoice is required.');
        };
        find('sequence-form').addEventListener('submit', event => {
            event.preventDefault();
            invalidate();
            try {
                const values = sequence(first.value, count.value);
                output.value = values.join('\n');
                summary.textContent = `${values.length} serial${values.length === 1 ? '' : 's'}: ${values[0]} → ${values[values.length - 1]}`;
                result.hidden = false; copy.disabled = false;
                message('Serial list generated. Copy it for use where needed. No database records were changed.');
            } catch (error) { message(error.message, true); }
        });
        copy.addEventListener('click', async () => {
            if (!output.value) return;
            const text = output.value;
            try {
                if (!clipboard?.writeText) throw Error('Clipboard unavailable');
                await clipboard.writeText(text);
                if (output.value === text) message('Serial list copied. No database records were changed.');
            } catch (_) {
                if (output.value !== text) return;
                output.focus(); output.select();
                message('Automatic copy is unavailable in this browser. The list is selected: press Ctrl+C (or Cmd+C) to copy.');
            }
        });
        for (const input of [first, count]) input.addEventListener('input', invalidate);
        invalidate();
    };
    const api = {validateSerial, sequence, attach};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    root.ReceivingSerials = api;
    if (typeof document !== 'undefined') {
        const host = document.getElementById('serial-tools');
        if (host) attach({host});
    }
})(globalThis);
