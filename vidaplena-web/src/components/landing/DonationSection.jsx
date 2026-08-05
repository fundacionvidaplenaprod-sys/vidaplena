import { Syringe, Stethoscope, HeartHandshake } from 'lucide-react';

const IMPACT_ITEMS = [
  { icon: Syringe, text: 'Insulina y tiras reactivas.' },
  { icon: Stethoscope, text: 'Consultas médicas y atención continua.' },
  { icon: HeartHandshake, text: 'Tranquilidad y esperanza para una familia.' },
];

export default function DonationSection({ qrDonaciones }) {
  return (
    <section id="donar" className="py-16 bg-green-50">
      <div className="container mx-auto px-6">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-center">

          {/* COLUMNA IZQUIERDA: COPY PERSUASIVO */}
          <div className="text-left max-w-prose order-1">
            <h2 className="text-3xl font-bold text-vida-primary mb-6">Apoya Nuestra Causa</h2>

            <p className="text-gray-700 mb-6">
              Para miles de personas convivir con la diabetes significa depender día a día de
              insumos, medicación y atención médica constante. En nuestra Fundación, trabajamos
              incansablemente para que nadie tenga que suspender su tratamiento por falta de
              recursos.
            </p>

            <p className="font-bold text-gray-800 mb-3">Tu donación se transforma directamente en:</p>
            <ul className="space-y-3 mb-6">
              {IMPACT_ITEMS.map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-center gap-3 text-gray-700">
                  <span className="flex-shrink-0 bg-green-100 text-vida-primary rounded-full p-2">
                    <Icon size={20} />
                  </span>
                  <span>{text}</span>
                </li>
              ))}
            </ul>

            <p className="text-gray-700">
              Súmate hoy. Con tu apoyo solidario, garantizas que más niños, jóvenes y adultos
              reciban la atención y el tratamiento que necesitan para vivir plenamente.
            </p>
          </div>

          {/* COLUMNA DERECHA: TARJETA DEL QR */}
          <div className="order-2">
            <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-8 flex flex-col items-center text-center max-w-sm mx-auto">
              <p className="text-gray-600 mb-6">
                Escanea el código QR para realizar tu donación de forma rápida y segura.
              </p>

              {qrDonaciones ? (
                <img src={qrDonaciones} alt="QR Donación" className="w-48 h-48 border p-2 bg-white rounded-lg" />
              ) : (
                <div className="w-48 h-48 border p-2 bg-white rounded-lg flex items-center justify-center text-gray-300 text-sm text-center">
                  QR no configurado
                </div>
              )}
            </div>
          </div>

        </div>
      </div>
    </section>
  );
}
