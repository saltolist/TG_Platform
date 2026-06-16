import type { PostMedia } from "@/shared/types";

/** Data-URL image for demo / presentation seeds (renders in PostMediaBlock like user uploads). */
export function svgMedia(name: string, svg: string): PostMedia {
  const trimmed = svg.trim();
  const safeName = /\.(jpe?g|png|webp|gif|svg)$/i.test(name) ? name : `${name}.jpg`;
  return {
    name: safeName,
    url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(trimmed)}`,
    type: "image/svg+xml",
  };
}

export type PostIllustrationTheme =
  | "workspace-hub"
  | "feed-timeline"
  | "feed-sections"
  | "notes-stack"
  | "ai-dialogue"
  | "chart-growth"
  | "heatmap-grid"
  | "clock-pending"
  | "calendar-slot"
  | "postpone-flow"
  | "scheduled-queue"
  | "draft-post-edit"
  | "draft-top-handle"
  | "draft-reorder";

const ILLUSTRATIONS: Record<PostIllustrationTheme, string> = {
  "workspace-hub": `
    <rect width='600' height='600' fill='#1a2030'/>
    <rect x='48' y='72' width='120' height='456' rx='18' fill='#252d42' stroke='#3d4a66' stroke-width='2'/>
    <rect x='68' y='104' width='80' height='12' rx='6' fill='#5b8ff9' opacity='0.9'/>
    <rect x='68' y='132' width='64' height='8' rx='4' fill='#4a5568'/>
    <rect x='68' y='152' width='72' height='8' rx='4' fill='#4a5568'/>
    <rect x='68' y='172' width='56' height='8' rx='4' fill='#4a5568'/>
    <rect x='192' y='72' width='360' height='200' rx='20' fill='#2a3348' stroke='#3d4a66' stroke-width='2'/>
    <rect x='220' y='108' width='180' height='14' rx='7' fill='#6eb5ff' opacity='0.85'/>
    <rect x='220' y='136' width='280' height='10' rx='5' fill='#4a5568'/>
    <rect x='220' y='158' width='240' height='10' rx='5' fill='#4a5568'/>
    <rect x='192' y='296' width='360' height='232' rx='20' fill='#2a3348' stroke='#3d4a66' stroke-width='2'/>
    <rect x='220' y='332' width='120' height='80' rx='12' fill='#3d4f6e'/>
    <rect x='356' y='332' width='120' height='80' rx='12' fill='#3d5a4a'/>
    <rect x='220' y='428' width='256' height='12' rx='6' fill='#5b8ff9' opacity='0.5'/>
    <circle cx='300' cy='300' r='88' fill='none' stroke='#5b8ff9' stroke-width='3' opacity='0.25'/>`,

  "feed-timeline": `
    <rect width='600' height='600' fill='#f4f6fa'/>
    <rect x='80' y='88' width='440' height='56' rx='12' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <rect x='104' y='108' width='120' height='10' rx='5' fill='#c5d0e0'/>
    <rect x='104' y='124' width='200' height='8' rx='4' fill='#e2e8f0'/>
    <rect x='80' y='164' width='440' height='120' rx='16' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <rect x='80' y='164' width='440' height='72' rx='16' fill='#d4e4ff'/>
    <rect x='104' y='252' width='160' height='10' rx='5' fill='#8aa4c8'/>
    <rect x='104' y='268' width='280' height='8' rx='4' fill='#c5d0e0'/>
    <rect x='80' y='304' width='440' height='120' rx='16' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <rect x='80' y='304' width='218' height='120' rx='16' fill='#c8f0d8'/>
    <rect x='302' y='304' width='218' height='120' rx='16' fill='#ffe4c8'/>
    <rect x='104' y='392' width='140' height='10' rx='5' fill='#8aa4c8'/>
    <rect x='80' y='444' width='440' height='72' rx='16' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <rect x='104' y='472' width='320' height='10' rx='5' fill='#c5d0e0'/>`,

  "feed-sections": `
    <rect width='600' height='600' fill='#eef1f6'/>
    <text x='300' y='118' text-anchor='middle' fill='#8b95a8' font-family='Inter,sans-serif' font-size='18' font-weight='600' letter-spacing='3'>ЛЕНТА</text>
    <rect x='100' y='148' width='400' height='88' rx='14' fill='#fff' stroke='#5b8ff9' stroke-width='2'/>
    <rect x='124' y='172' width='24' height='24' rx='6' fill='#5b8ff9' opacity='0.2'/>
    <path d='M132 184l6 6 10-12' stroke='#5b8ff9' stroke-width='2.5' fill='none' stroke-linecap='round'/>
    <rect x='160' y='176' width='180' height='12' rx='6' fill='#3d4a66'/>
    <rect x='160' y='198' width='120' height='8' rx='4' fill='#c5d0e0'/>
    <rect x='100' y='260' width='400' height='88' rx='14' fill='#fff' stroke='#f39c12' stroke-width='2'/>
    <circle cx='136' cy='304' r='14' fill='#f39c12' opacity='0.2'/>
    <circle cx='136' cy='304' r='8' fill='none' stroke='#f39c12' stroke-width='2'/>
    <path d='M136 300v5l3 2' stroke='#f39c12' stroke-width='2' stroke-linecap='round'/>
    <rect x='160' y='288' width='160' height='12' rx='6' fill='#3d4a66'/>
    <rect x='160' y='310' width='100' height='8' rx='4' fill='#c5d0e0'/>
    <rect x='100' y='372' width='400' height='88' rx='14' fill='#fff' stroke='#95a5a6' stroke-width='2' stroke-dasharray='8 6'/>
    <rect x='124' y='396' width='24' height='24' rx='6' fill='#95a5a6' opacity='0.25'/>
    <rect x='160' y='400' width='170' height='12' rx='6' fill='#6b7280'/>
    <rect x='160' y='422' width='130' height='8' rx='4' fill='#c5d0e0'/>`,

  "notes-stack": `
    <rect width='600' height='600' fill='#1e2433'/>
    <rect x='140' y='100' width='320' height='400' rx='16' fill='#2d3548' stroke='#4a5568' stroke-width='2' transform='rotate(-6 300 300)'/>
    <rect x='120' y='120' width='320' height='400' rx='16' fill='#343d52' stroke='#5b8ff9' stroke-width='2' transform='rotate(3 300 300)'/>
    <rect x='100' y='140' width='320' height='400' rx='16' fill='#3d4760'/>
    <rect x='136' y='188' width='200' height='14' rx='7' fill='#6eb5ff'/>
    <rect x='136' y='220' width='248' height='8' rx='4' fill='#5a6478'/>
    <rect x='136' y='240' width='220' height='8' rx='4' fill='#5a6478'/>
    <rect x='136' y='260' width='236' height='8' rx='4' fill='#5a6478'/>
    <rect x='136' y='300' width='120' height='36' rx='8' fill='#5b8ff9' opacity='0.25' stroke='#5b8ff9' stroke-width='1.5'/>
    <text x='196' y='324' text-anchor='middle' fill='#8ec0ff' font-family='Inter,sans-serif' font-size='14' font-weight='600'>AI</text>
    <circle cx='400' cy='460' r='48' fill='#5b8ff9' opacity='0.15'/>`,

  "ai-dialogue": `
    <rect width='600' height='600' fill='#12182a'/>
    <rect x='72' y='140' width='280' height='88' rx='20' fill='#2a3550'/>
    <rect x='96' y='168' width='200' height='10' rx='5' fill='#8b9bb8'/>
    <rect x='96' y='188' width='160' height='8' rx='4' fill='#5a6478'/>
    <rect x='248' y='260' width='280' height='120' rx='20' fill='#1e3a5f' stroke='#5b8ff9' stroke-width='2'/>
    <rect x='272' y='288' width='220' height='10' rx='5' fill='#8ec0ff'/>
    <rect x='272' y='308' width='180' height='8' rx='4' fill='#6b8cb8'/>
    <rect x='272' y='324' width='200' height='8' rx='4' fill='#6b8cb8'/>
    <circle cx='300' cy='96' r='36' fill='#5b8ff9' opacity='0.2'/>
    <path d='M288 88h24M300 76v24' stroke='#5b8ff9' stroke-width='3' stroke-linecap='round'/>
    <circle cx='120' cy='420' r='6' fill='#5b8ff9' opacity='0.6'/>
    <circle cx='148' cy='420' r='6' fill='#5b8ff9' opacity='0.4'/>
    <circle cx='176' cy='420' r='6' fill='#5b8ff9' opacity='0.25'/>`,

  "chart-growth": `
    <defs>
      <linearGradient id='cg' x1='0' y1='0' x2='0' y2='1'>
        <stop offset='0' stop-color='#5b8ff9' stop-opacity='0.35'/>
        <stop offset='1' stop-color='#5b8ff9' stop-opacity='0'/>
      </linearGradient>
    </defs>
    <rect width='600' height='600' fill='#0f1419'/>
    <rect x='80' y='100' width='440' height='400' rx='20' fill='#1a222d' stroke='#2d3748' stroke-width='2'/>
    <line x1='120' y1='440' x2='480' y2='440' stroke='#3d4a5c' stroke-width='2'/>
    <line x1='120' y1='140' x2='120' y2='440' stroke='#3d4a5c' stroke-width='2'/>
    <polyline points='140,380 200,340 260,360 320,280 380,240 440,180' fill='none' stroke='#5b8ff9' stroke-width='4' stroke-linecap='round' stroke-linejoin='round'/>
    <polygon points='140,380 200,340 260,360 320,280 380,240 440,180 440,440 140,440' fill='url(#cg)'/>
    <circle cx='440' cy='180' r='10' fill='#5b8ff9'/>
    <rect x='140' y='468' width='48' height='8' rx='4' fill='#4a5568'/>
    <rect x='220' y='468' width='48' height='8' rx='4' fill='#4a5568'/>
    <rect x='300' y='468' width='48' height='8' rx='4' fill='#4a5568'/>
    <rect x='380' y='468' width='48' height='8' rx='4' fill='#4a5568'/>`,

  "heatmap-grid": `
    <rect width='600' height='600' fill='#141820'/>
    <rect x='100' y='120' width='400' height='360' rx='16' fill='#1e2530' stroke='#2d3748' stroke-width='2'/>
    <g transform='translate(130,160)'>
      ${[0.2, 0.5, 0.9, 0.4, 0.7, 0.3, 0.85, 0.55, 0.25, 0.65, 0.45, 0.8, 0.35, 0.95, 0.5, 0.6, 0.75, 0.4, 0.9, 0.3, 0.7, 0.55, 0.85, 0.45, 0.6, 0.8, 0.35, 0.7].map((o, i) => {
        const col = i % 7;
        const row = Math.floor(i / 7);
        const hue = Math.round(200 + o * 60);
        return `<rect x='${col * 48}' y='${row * 48}' width='40' height='40' rx='6' fill='hsl(${hue},70%,${35 + o * 25}%)' opacity='${0.5 + o * 0.5}'/>`;
      }).join("")}
    </g>
    <rect x='130' y='500' width='80' height='10' rx='5' fill='#4a5568'/>
    <rect x='360' y='500' width='120' height='10' rx='5' fill='#5b8ff9' opacity='0.6'/>`,

  "clock-pending": `
    <rect width='600' height='600' fill='#1a2535'/>
    <circle cx='300' cy='280' r='140' fill='#243044' stroke='#f39c12' stroke-width='6'/>
    <circle cx='300' cy='280' r='8' fill='#f39c12'/>
    <line x1='300' y1='280' x2='300' y2='180' stroke='#fff' stroke-width='6' stroke-linecap='round'/>
    <line x1='300' y1='280' x2='370' y2='310' stroke='#f39c12' stroke-width='5' stroke-linecap='round'/>
    <rect x='180' y='460' width='240' height='72' rx='16' fill='#2a3848' stroke='#f39c12' stroke-width='2'/>
    <text x='300' y='506' text-anchor='middle' fill='#f39c12' font-family='Inter,sans-serif' font-size='28' font-weight='700'>14 июн · 12:00</text>`,
  "calendar-slot": `
    <rect width='600' height='600' fill='#f8f9fc'/>
    <rect x='100' y='80' width='400' height='440' rx='20' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <rect x='100' y='80' width='400' height='64' rx='20' fill='#5b8ff9'/>
    <rect x='100' y='120' width='400' height='24' fill='#5b8ff9'/>
    <text x='300' y='122' text-anchor='middle' fill='#fff' font-family='Inter,sans-serif' font-size='22' font-weight='700'>ИЮНЬ</text>
    <g fill='#e8edf5'>
      ${Array.from({ length: 28 }, (_, i) => {
        const col = i % 7;
        const row = Math.floor(i / 7);
        const highlighted = i === 13 || i === 16;
        return `<rect x='${128 + col * 48}' y='${168 + row * 52}' width='40' height='40' rx='8' fill='${highlighted ? "#5b8ff9" : "#eef2f8"}'/>`;
      }).join("")}
    </g>
    <circle cx='320' cy='376' r='6' fill='#fff'/>
    <circle cx='464' cy='428' r='6' fill='#fff'/>`,

  "postpone-flow": `
    <rect width='600' height='600' fill='#eef2f8'/>
    <rect x='88' y='120' width='160' height='100' rx='14' fill='#fff' stroke='#95a5a6' stroke-width='2' stroke-dasharray='6 4'/>
    <text x='168' y='178' text-anchor='middle' fill='#6b7280' font-family='Inter,sans-serif' font-size='14' font-weight='600'>Черновик</text>
    <path d='M260 170h60' stroke='#5b8ff9' stroke-width='3' marker-end='url(#arr)'/>
    <defs><marker id='arr' markerWidth='8' markerHeight='8' refX='6' refY='4' orient='auto'><path d='M0,0 L8,4 L0,8' fill='#5b8ff9'/></marker></defs>
    <rect x='332' y='120' width='180' height='100' rx='14' fill='#fff3e0' stroke='#f39c12' stroke-width='2'/>
    <circle cx='372' cy='160' r='14' fill='#f39c12' opacity='0.2'/>
    <path d='M372 152v10l6 4' stroke='#f39c12' stroke-width='2' stroke-linecap='round'/>
    <text x='422' y='178' text-anchor='middle' fill='#c87d0a' font-family='Inter,sans-serif' font-size='14' font-weight='600'>Отложить</text>
    <path d='M300 250v40' stroke='#5b8ff9' stroke-width='3'/>
    <path d='M280 270l20 20 20-20' stroke='#5b8ff9' stroke-width='3' fill='none' stroke-linecap='round'/>
    <rect x='160' y='310' width='280' height='120' rx='16' fill='#fff' stroke='#f39c12' stroke-width='2'/>
    <rect x='188' y='342' width='224' height='12' rx='6' fill='#3d4a66'/>
    <rect x='188' y='364' width='160' height='8' rx='4' fill='#f39c12' opacity='0.5'/>
    <text x='300' y='400' text-anchor='middle' fill='#f39c12' font-family='Inter,sans-serif' font-size='16' font-weight='600'>17 июн · 18:00</text>`,

  "scheduled-queue": `
    <rect width='600' height='600' fill='#1c2230'/>
    <text x='300' y='108' text-anchor='middle' fill='#8b95a8' font-family='Inter,sans-serif' font-size='16' font-weight='600' letter-spacing='2'>ОТЛОЖЕННЫЕ</text>
    <rect x='100' y='140' width='400' height='96' rx='14' fill='#2a3348' stroke='#f39c12' stroke-width='2'/>
    <circle cx='148' cy='188' r='18' fill='#f39c12' opacity='0.2'/>
    <path d='M148 180v10l7 4' stroke='#f39c12' stroke-width='2' stroke-linecap='round'/>
    <rect x='180' y='172' width='200' height='12' rx='6' fill='#c8d4e8'/>
    <rect x='180' y='194' width='140' height='8' rx='4' fill='#5a6478'/>
  <rect x='100' y='256' width='400' height='96' rx='14' fill='#2a3348' stroke='#4a5568' stroke-width='2'/>
    <circle cx='148' cy='304' r='18' fill='#5b8ff9' opacity='0.2'/>
    <path d='M148 296v10l7 4' stroke='#5b8ff9' stroke-width='2' stroke-linecap='round'/>
    <rect x='180' y='288' width='180' height='12' rx='6' fill='#8b9bb8'/>
    <rect x='180' y='310' width='120' height='8' rx='4' fill='#5a6478'/>`,

  "draft-post-edit": `
    <rect width='600' height='600' fill='#eef1f6'/>
    <rect x='80' y='72' width='440' height='340' rx='16' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <rect x='80' y='72' width='440' height='96' rx='16' fill='#d4e4ff'/>
    <rect x='104' y='188' width='280' height='14' rx='7' fill='#3d4a66'/>
    <rect x='104' y='214' width='360' height='10' rx='5' fill='#c5d0e0'/>
    <rect x='104' y='234' width='320' height='10' rx='5' fill='#c5d0e0'/>
    <rect x='104' y='254' width='240' height='10' rx='5' fill='#d1d5db'/>
    <rect x='104' y='280' width='3' height='28' rx='1.5' fill='#5b8ff9'/>
    <text x='120' y='302' fill='#95a5a6' font-family='Inter,sans-serif' font-size='14' font-style='italic'>дописать мысль…</text>
    <text x='104' y='348' fill='#95a5a6' font-family='Inter,sans-serif' font-size='13' font-weight='500'>✎ Черновик</text>
    <rect x='80' y='428' width='440' height='72' rx='14' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <rect x='104' y='452' width='36' height='36' rx='8' fill='#eef2f8' stroke='#c5d0e0' stroke-width='1.5'/>
    <path d='M116 464h20M122 458v20' stroke='#6b7280' stroke-width='2' stroke-linecap='round'/>
    <rect x='300' y='456' width='100' height='32' rx='8' fill='#eef2f8' stroke='#c5d0e0' stroke-width='1.5'/>
    <text x='350' y='478' text-anchor='middle' fill='#6b7280' font-family='Inter,sans-serif' font-size='14' font-weight='600'>Отмена</text>
    <rect x='412' y='456' width='84' height='32' rx='8' fill='#5b8ff9'/>
    <text x='454' y='478' text-anchor='middle' fill='#fff' font-family='Inter,sans-serif' font-size='14' font-weight='600'>Сохранить</text>`,

  "draft-top-handle": `
    <rect width='600' height='600' fill='#252b38'/>
    <rect x='100' y='140' width='400' height='280' rx='16' fill='#343d4f' stroke='#5b8ff9' stroke-width='2'/>
    <rect x='268' y='118' width='64' height='36' rx='10' fill='#2a3348' stroke='#5b8ff9' stroke-width='2'/>
    <g fill='#8ec0ff'>
      <circle cx='286' cy='130' r='4'/><circle cx='300' cy='130' r='4'/><circle cx='314' cy='130' r='4'/>
      <circle cx='286' cy='142' r='4'/><circle cx='300' cy='142' r='4'/><circle cx='314' cy='142' r='4'/>
    </g>
    <rect x='136' y='200' width='220' height='14' rx='7' fill='#a8b4c8'/>
    <rect x='136' y='226' width='300' height='8' rx='4' fill='#5a6478'/>
    <rect x='136' y='246' width='260' height='8' rx='4' fill='#5a6478'/>
    <rect x='136' y='266' width='200' height='8' rx='4' fill='#5a6478'/>
    <path d='M300 88v24' stroke='#5b8ff9' stroke-width='3' stroke-linecap='round'/>
    <path d='M300 460v28' stroke='#5b8ff9' stroke-width='4' stroke-linecap='round' opacity='0.7'/>
    <polygon points='300,496 288,472 312,472' fill='#5b8ff9' opacity='0.7'/>
    <ellipse cx='300' cy='108' rx='22' ry='14' fill='none' stroke='#5b8ff9' stroke-width='2' opacity='0.5'/>`,

  "draft-reorder": `
    <rect width='600' height='600' fill='#eef1f6'/>
    <rect x='100' y='100' width='400' height='88' rx='14' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <g fill='#9ca3af'>
      <circle cx='286' cy='118' r='4'/><circle cx='300' cy='118' r='4'/><circle cx='314' cy='118' r='4'/>
      <circle cx='286' cy='130' r='4'/><circle cx='300' cy='130' r='4'/><circle cx='314' cy='130' r='4'/>
    </g>
    <rect x='128' y='148' width='160' height='10' rx='5' fill='#9ca3af'/>
    <path d='M300 200v28' stroke='#5b8ff9' stroke-width='3'/>
    <polygon points='300,236 288,216 312,216' fill='#5b8ff9'/>
    <rect x='100' y='248' width='400' height='88' rx='14' fill='#fff' stroke='#5b8ff9' stroke-width='2'/>
    <g fill='#5b8ff9'>
      <circle cx='286' cy='266' r='4'/><circle cx='300' cy='266' r='4'/><circle cx='314' cy='266' r='4'/>
      <circle cx='286' cy='278' r='4'/><circle cx='300' cy='278' r='4'/><circle cx='314' cy='278' r='4'/>
    </g>
    <rect x='128' y='296' width='190' height='10' rx='5' fill='#3d4a66'/>
    <path d='M300 348v28' stroke='#5b8ff9' stroke-width='3'/>
    <polygon points='300,384 288,364 312,364' fill='#5b8ff9'/>
    <rect x='100' y='396' width='400' height='88' rx='14' fill='#fff' stroke='#dde3ee' stroke-width='2'/>
    <g fill='#9ca3af'>
      <circle cx='286' cy='414' r='4'/><circle cx='300' cy='414' r='4'/><circle cx='314' cy='414' r='4'/>
      <circle cx='286' cy='426' r='4'/><circle cx='300' cy='426' r='4'/><circle cx='314' cy='426' r='4'/>
    </g>
    <rect x='128' y='444' width='150' height='10' rx='5' fill='#9ca3af'/>`,
};

function wrapIllustration(inner: string): string {
  return `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 600'>${inner}</svg>`;
}

/** Themed UI illustration for presentation / demo posts (max 2 per post). */
export function themedPostMedia(filename: string, theme: PostIllustrationTheme): PostMedia {
  return svgMedia(filename, wrapIllustration(ILLUSTRATIONS[theme]));
}

/** @deprecated Use themedPostMedia — kept for demo-full seed compatibility */
export type TelegramPhotoScene =
  | "sky"
  | "forest"
  | "sunset"
  | "ocean"
  | "lavender"
  | "amber"
  | "slate"
  | "rose";

const LEGACY_SCENE_TO_THEME: Record<TelegramPhotoScene, PostIllustrationTheme> = {
  sky: "workspace-hub",
  forest: "feed-timeline",
  sunset: "chart-growth",
  ocean: "ai-dialogue",
  lavender: "notes-stack",
  amber: "clock-pending",
  slate: "draft-post-edit",
  rose: "heatmap-grid",
};

export function telegramPhotoMedia(filename: string, scene: TelegramPhotoScene): PostMedia {
  return themedPostMedia(filename, LEGACY_SCENE_TO_THEME[scene]);
}
