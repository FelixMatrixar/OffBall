import type { Lang } from '../prefs';

/** Short labels drawn on the pitch. Placeholders: {num}, {name}, {speed}, {m}, {pts}. */
export interface PitchLabels {
  spaceOpens: string;
  gapShut: string;
  no: string;
  named: string;
  follows: string;
  decoy: string;
  sprint: string;
  line: string;
  gapZone: string;
  noRun: string;
  stays: string;
  correction: string;
}

export const LABELS: Record<Lang, PitchLabels> = {
  en: { spaceOpens: 'Space opens here', gapShut: 'Gap stays shut', no: 'No. {num}', named: 'No. {num} {name}', follows: 'No. {num} follows', decoy: '{num} · decoy run', sprint: 'Sprint {speed} km/h', line: 'Ashmoor line · {m} m', gapZone: 'Gap zone · {pts} pts', noRun: '{num} · no run', stays: '{num} · stays', correction: 'Correction' },
  es: { spaceOpens: 'Aquí se abre el espacio', gapShut: 'El hueco sigue cerrado', no: 'N.º {num}', named: 'N.º {num} {name}', follows: 'El {num} lo sigue', decoy: '{num} · desmarque de arrastre', sprint: 'Sprint {speed} km/h', line: 'Línea de Ashmoor · {m} m', gapZone: 'Zona del hueco · {pts} pts', noRun: '{num} · sin desmarque', stays: '{num} · se queda', correction: 'Corrección' },
  pt: { spaceOpens: 'O espaço se abre aqui', gapShut: 'O espaço continua fechado', no: 'N.º {num}', named: 'N.º {num} {name}', follows: 'O {num} acompanha', decoy: '{num} · corrida de arrasto', sprint: 'Sprint {speed} km/h', line: 'Linha do Ashmoor · {m} m', gapZone: 'Zona do espaço · {pts} pts', noRun: '{num} · sem corrida', stays: '{num} · fica', correction: 'Correção' },
  fr: { spaceOpens: 'L’espace s’ouvre ici', gapShut: 'L’espace reste fermé', no: 'N° {num}', named: 'N° {num} {name}', follows: 'Le n° {num} suit', decoy: '{num} · appel leurre', sprint: 'Sprint {speed} km/h', line: 'Ligne d’Ashmoor · {m} m', gapZone: 'Zone libre · {pts} pts', noRun: '{num} · sans appel', stays: '{num} · reste', correction: 'Correction' },
  ar: { spaceOpens: 'هنا تنفتح المساحة', gapShut: 'المساحة تبقى مغلقة', no: 'رقم {num}', named: 'رقم {num} {name}', follows: 'رقم {num} يتبعه', decoy: '{num} · ركضة خادعة', sprint: 'انطلاقة {speed} كم/س', line: 'خط أشمور · {m} م', gapZone: 'منطقة المساحة · {pts} نقطة', noRun: '{num} · بلا ركض', stays: '{num} · يبقى', correction: 'تصحيح' },
  hi: { spaceOpens: 'यहाँ जगह खुलती है', gapShut: 'गैप बंद रहता है', no: 'नं. {num}', named: 'नं. {num} {name}', follows: 'नं. {num} पीछे जाता है', decoy: '{num} · डिकॉय रन', sprint: 'स्प्रिंट {speed} किमी/घं.', line: 'ऐशमूर लाइन · {m} मी.', gapZone: 'गैप ज़ोन · {pts} अंक', noRun: '{num} · बिना दौड़', stays: '{num} · टिका रहता है', correction: 'सुधार' },
  id: { spaceOpens: 'Ruang terbuka di sini', gapShut: 'Celah tetap tertutup', no: 'No. {num}', named: 'No. {num} {name}', follows: 'No. {num} mengikuti', decoy: '{num} · lari pancingan', sprint: 'Sprint {speed} km/jam', line: 'Garis Ashmoor · {m} m', gapZone: 'Zona celah · {pts} poin', noRun: '{num} · tanpa lari', stays: '{num} · bertahan', correction: 'Koreksi' },
  zh: { spaceOpens: '空间在这里打开', gapShut: '空当没有出现', no: '{num}号', named: '{num}号 {name}', follows: '{num}号跟防', decoy: '{num} · 牵制跑动', sprint: '冲刺 {speed} 公里/小时', line: '阿什穆尔防线 · {m}米', gapZone: '空当区 · {pts}分', noRun: '{num} · 不跑动', stays: '{num} · 留守', correction: '更正' },
  ja: { spaceOpens: 'ここにスペースが生まれる', gapShut: 'スペースは閉じたまま', no: '{num}番', named: '{num}番 {name}', follows: '{num}番がついていく', decoy: '{num} · おとりのラン', sprint: 'スプリント 時速{speed}km', line: 'アッシュムーアのライン · {m}m', gapZone: 'ギャップゾーン · {pts}pt', noRun: '{num} · ランなし', stays: '{num} · 残る', correction: '訂正' },
  sw: { spaceOpens: 'Nafasi inafunguka hapa', gapShut: 'Nafasi inabaki imefungwa', no: 'Namba {num}', named: 'Namba {num} {name}', follows: 'Namba {num} anafuata', decoy: '{num} · mbio za udanganyifu', sprint: 'Kasi km {speed} kwa saa', line: 'Mstari wa Ashmoor · mita {m}', gapZone: 'Eneo la nafasi · alama {pts}', noRun: '{num} · bila mbio', stays: '{num} · anabaki', correction: 'Marekebisho' },
};
