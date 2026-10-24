import { useNow } from '../../lib/hooks';
import { pairUrl } from '../../lib/pairing';
import { Button, Dialog, PulseDot, QrCode } from '../ui';

interface Props {
  open: boolean;
  onClose: () => void;
  code: string;
  expiresAt: number;
  guests: number;
  onRenew: () => void;
}

/** Pair a phone (PRD 15.5): a 6-character code or a QR code, valid for 2 hours, that identifies nobody. */
export function PairDialog({ open, onClose, code, expiresAt, guests, onRenew }: Props) {
  const now = useNow(1000);
  const left = Math.max(0, expiresAt - now);
  const h = Math.floor(left / 3_600_000);
  const m = Math.floor((left % 3_600_000) / 60_000);
  return (
    <Dialog open={open} onClose={onClose} title="Pair a phone">
      <div className="cluster" style={{ alignItems: 'flex-start', gap: 20 }}>
        <QrCode value={pairUrl(code)} label={`QR code that opens the OffBall companion paired with code ${code.split('').join(' ')}`} />
        <div className="stack" style={{ flex: '1 1 220px' }}>
          <p className="muted" style={{ fontSize: 14 }}>
            Scan the code with your phone’s camera, or open the companion and type:
          </p>
          <p className="display tabular" style={{ fontSize: 44, letterSpacing: '0.18em' }} aria-label={`Code ${code.split('').join(' ')}`}>
            {code}
          </p>
          <p className="muted" style={{ fontSize: 13 }}>
            Expires in {h} h {m} min. Nothing in the code identifies you.
          </p>
          <p className="cluster" style={{ gap: 8, fontSize: 14 }} role="status">
            {guests > 0 ? (
              <>
                <PulseDot size={8} /> {guests === 1 ? 'One phone paired' : `${guests} phones paired`}
              </>
            ) : (
              'No phone paired yet'
            )}
          </p>
          <div className="cluster">
            <Button variant="ghost" className="btn-sm" onClick={onRenew}>
              New code
            </Button>
            <a className="btn btn-ghost btn-sm press" href={pairUrl(code)} target="_blank" rel="noreferrer">
              Open the companion here
            </a>
          </div>
        </div>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Pairing works between tabs on this device today. Pairing across devices joins a Web PubSub group once the live service runs.
      </p>
    </Dialog>
  );
}
