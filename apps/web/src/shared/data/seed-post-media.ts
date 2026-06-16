import { svgMedia } from "@/shared/data/demo-media";

export const mediaFirstStep = svgMedia(
  "Первый шаг.svg",
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 600'>
    <defs>
      <linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>
        <stop offset='0' stop-color='#5b8ff9'/>
        <stop offset='1' stop-color='#7b5bf9'/>
      </linearGradient>
    </defs>
    <rect width='600' height='600' fill='url(#g)'/>
    <circle cx='300' cy='270' r='140' fill='rgba(255,255,255,0.18)'/>
    <text x='300' y='335' text-anchor='middle' fill='white' font-family='Inter,-apple-system,sans-serif' font-size='190' font-weight='700'>₽</text>
    <text x='300' y='465' text-anchor='middle' fill='rgba(255,255,255,0.85)' font-family='Inter,-apple-system,sans-serif' font-size='28' font-weight='500' letter-spacing='3'>ПЕРВЫЙ ШАГ</text>
  </svg>`,
);

export const mediaIisA = svgMedia(
  "ИИС тип А.svg",
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 600'>
    <defs>
      <linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>
        <stop offset='0' stop-color='#1f9d5b'/>
        <stop offset='1' stop-color='#0e6b3e'/>
      </linearGradient>
    </defs>
    <rect width='600' height='600' fill='url(#g)'/>
    <text x='300' y='220' text-anchor='middle' fill='rgba(255,255,255,0.85)' font-family='Inter,-apple-system,sans-serif' font-size='30' font-weight='500' letter-spacing='4'>ИИС · ТИП А</text>
    <text x='300' y='350' text-anchor='middle' fill='white' font-family='Inter,-apple-system,sans-serif' font-size='90' font-weight='800'>52 000 ₽</text>
    <text x='300' y='415' text-anchor='middle' fill='rgba(255,255,255,0.85)' font-family='Inter,-apple-system,sans-serif' font-size='24' font-weight='500'>возврат налога / год</text>
  </svg>`,
);

export const mediaIisB = svgMedia(
  "ИИС тип Б.svg",
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 600'>
    <defs>
      <linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>
        <stop offset='0' stop-color='#1c7ec6'/>
        <stop offset='1' stop-color='#0c5293'/>
      </linearGradient>
    </defs>
    <rect width='600' height='600' fill='url(#g)'/>
    <text x='300' y='220' text-anchor='middle' fill='rgba(255,255,255,0.85)' font-family='Inter,-apple-system,sans-serif' font-size='30' font-weight='500' letter-spacing='4'>ИИС · ТИП Б</text>
    <text x='300' y='370' text-anchor='middle' fill='white' font-family='Inter,-apple-system,sans-serif' font-size='150' font-weight='800'>0%</text>
    <text x='300' y='435' text-anchor='middle' fill='rgba(255,255,255,0.85)' font-family='Inter,-apple-system,sans-serif' font-size='24' font-weight='500'>налога на прибыль</text>
  </svg>`,
);

export const mediaBuyButton = svgMedia(
  "Кнопка Купить.svg",
  `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 600'>
    <defs>
      <linearGradient id='bg' x1='0' y1='0' x2='1' y2='1'>
        <stop offset='0' stop-color='#222'/>
        <stop offset='1' stop-color='#3a3a3a'/>
      </linearGradient>
      <linearGradient id='btn' x1='0' y1='0' x2='1' y2='0'>
        <stop offset='0' stop-color='#33b96b'/>
        <stop offset='1' stop-color='#5ed68d'/>
      </linearGradient>
    </defs>
    <rect width='600' height='600' fill='url(#bg)'/>
    <rect x='100' y='240' width='400' height='120' rx='24' fill='url(#btn)'/>
    <text x='300' y='320' text-anchor='middle' fill='white' font-family='Inter,-apple-system,sans-serif' font-size='44' font-weight='700'>Купить</text>
    <text x='300' y='460' text-anchor='middle' fill='rgba(255,255,255,0.55)' font-family='Inter,-apple-system,sans-serif' font-size='22' font-weight='500' letter-spacing='2'>ПЕРВАЯ СДЕЛКА</text>
  </svg>`,
);
