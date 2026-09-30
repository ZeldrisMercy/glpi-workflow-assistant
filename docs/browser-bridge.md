# Browser Bridge

Source is in `extension/`; manifest version is 2.4.0. The extension captures structured blocks, originating timestamps and images, preserves logical evidence IDs and transfers handoffs to `127.0.0.1:8765` after local pairing.

Built-in host permissions include ChatGPT, Gemini, localhost and WhatsApp Web. Optional access to other HTTPS providers is broad and should be granted only for the provider actually needed. The extension transports data; it does not contain a GLPI API token.

The package script creates a Chromium archive using `importScripts` and declares Chrome 148 minimum. A Firefox developer XPI is also produced without Mozilla signing. Inspect installation requirements for your browser before using it.
