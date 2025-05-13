const https = require('https');

const PROJECT_NAME = 'your-glitch-project-name';  // ضع هنا اسم مشروعك على Glitch
const URL = 'https://${PROJECT_NAME}.glitch.me/wake';

function keepAlive() {
    https.get(URL, (res) => {
        console.log(`Pinged ${URL} with status: ${res.statusCode}`);
    }).on('error', (err) => {
        console.error(`Error pinging: ${err.message}`);
    });
}

// استمر في إرسال ping كل 5 دقائق
setInterval(keepAlive, 5 * 60 * 1000);  // كل 5 دقائق