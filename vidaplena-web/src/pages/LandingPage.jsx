import React from 'react';
import { Link } from 'react-router-dom';
import logoImg from '../assets/logo.png';
import logoportadaImg from '../assets/logoportada.jpeg';

export default function LandingPage() {
  return (
    <>
      {/* NAVBAR */}
      <nav className="fixed w-full bg-white shadow-md z-50">
        <div className="container mx-auto flex justify-between items-center p-4">
          
          {/* Logo */}
          <div className="flex items-center space-x-2">
            <img src={logoImg} alt="Logo Fundación" className="h-12" />
          </div>

          {/* Menú */}
          <div className="hidden md:flex space-x-6 items-center">
            <a href="#inicio" className="hover:text-green-800">Inicio</a>
            <a href="#nosotros" className="hover:text-green-800">Nosotros</a>
            <a href="#galeria" className="hover:text-green-800">Galería</a>
            <a href="#donar" className="hover:text-green-800">Donar</a>
          </div>

          {/* Botón especial (Visible en Móvil y Desktop) */}
          <div className="flex items-center">
            <Link to="/login" className="border-2 border-green-900 text-green-900 px-3 py-1.5 md:px-4 md:py-2 rounded-full hover:bg-green-900 hover:text-white transition text-sm md:text-base font-semibold">
              Acceso al Sistema
            </Link>
          </div>
        </div>
      </nav>

      {/* HERO */}
      <section id="inicio" className="h-screen bg-cover bg-center relative" style={{ backgroundImage: `url(${logoportadaImg})` }}>
        
        {/* Overlay */}
        <div className="absolute inset-0 bg-black bg-opacity-60"></div>

        <div className="relative z-10 flex flex-col justify-center items-center h-full text-center text-white px-4">
          <h1 className="text-4xl md:text-6xl font-bold mb-4">
            Salud y Esperanza para el Paciente Diabético
          </h1>

          <p className="text-lg md:text-2xl mb-6">
            Gestión transparente y dotación de insulinas de donación
          </p>

          <a href="#donar" className="bg-orange-600 hover:bg-orange-700 px-6 py-3 rounded-full text-lg font-semibold transition">
            Donar Ahora
          </a>
        </div>
      </section>

      {/* NOSOTROS */}
      <section id="nosotros" className="py-16 bg-gray-100">
        <div className="container mx-auto px-6">

          {/* Historia */}
          <div className="mb-12 text-center max-w-3xl mx-auto">
            <h2 className="text-3xl font-bold text-green-900 mb-4">Nuestra Historia</h2>
            <p className="text-gray-700">
              La Fundación Vida Plena nace como una iniciativa solidaria orientada a brindar apoyo a personas con diabetes que enfrentan dificultades para acceder a tratamientos esenciales. A través de la gestión transparente de donaciones, la fundación garantiza la distribución oportuna de insulina, promoviendo una mejor calidad de vida y fomentando la conciencia social sobre esta condición.
            </p>
          </div>

          {/* Misión, Visión, Objetivos */}
          <div className="grid md:grid-cols-3 gap-8">

            <div className="bg-white p-6 rounded-xl shadow text-center">
              <i className="fas fa-heart text-4xl text-green-900 mb-4"></i>
              <h3 className="text-xl font-bold mb-2">Misión</h3>
              <p>Gestionar y distribuir insulina de manera eficiente y transparente a quienes más lo necesitan.</p>
            </div>

            <div className="bg-white p-6 rounded-xl shadow text-center">
              <i className="fas fa-eye text-4xl text-green-900 mb-4"></i>
              <h3 className="text-xl font-bold mb-2">Visión</h3>
              <p>Ser una organización referente en apoyo integral a pacientes diabéticos en la región.</p>
            </div>

            <div className="bg-white p-6 rounded-xl shadow text-center">
              <i className="fas fa-bullseye text-4xl text-green-900 mb-4"></i>
              <h3 className="text-xl font-bold mb-2">Objetivos</h3>
              <p>Promover la solidaridad, el acceso a la salud y la sostenibilidad en la atención médica.</p>
            </div>

          </div>
        </div>
      </section>

      {/* GALERÍA */}
      <section id="galeria" className="py-16">
        <div className="container mx-auto px-6 text-center">

          <h2 className="text-3xl font-bold text-green-900 mb-10">Galería</h2>

          <div className="grid md:grid-cols-3 gap-6">
            <div className="bg-gray-300 h-48 rounded-lg"></div>
            <div className="bg-gray-300 h-48 rounded-lg"></div>
            <div className="bg-gray-300 h-48 rounded-lg"></div>
            <div className="bg-gray-300 h-48 rounded-lg"></div>
            <div className="bg-gray-300 h-48 rounded-lg"></div>
            <div className="bg-gray-300 h-48 rounded-lg"></div>
          </div>

        </div>
      </section>

      {/* DONACIONES */}
      <section id="donar" className="py-16 bg-green-50">
        <div className="container mx-auto px-6 text-center">

          <h2 className="text-3xl font-bold text-green-900 mb-6">Apoya Nuestra Causa</h2>

          <p className="mb-8">
            Escanea el código QR para realizar tu donación de forma rápida y segura.
          </p>

          <div className="flex justify-center mb-6">
            <img src="/qr-donacion.png" alt="QR Donación" className="w-48 h-48 border p-2 bg-white" />
          </div>

          <p className="text-gray-600">
            Tu aporte contribuye directamente a salvar vidas mediante el acceso a insulina.
          </p>

        </div>
      </section>

      {/* CONTACTO */}
      <section id="contacto" className="py-16">
        <div className="container mx-auto px-6">

          <h2 className="text-3xl font-bold text-green-900 text-center mb-10">Contacto</h2>

          <div className="grid md:grid-cols-2 gap-10">

            {/* Formulario */}
            <form className="space-y-4">
              <input type="text" placeholder="Nombre" className="w-full p-3 border rounded" />
              <input type="email" placeholder="Email" className="w-full p-3 border rounded" />
              <textarea placeholder="Mensaje" className="w-full p-3 border rounded"></textarea>

              <button className="bg-orange-600 text-white px-6 py-3 rounded hover:bg-orange-700 transition">
                Enviar Mensaje
              </button>
            </form>

            {/* Info */}
            <div>
              <p className="mb-4"><i className="fas fa-phone mr-2"></i> +591 70000000</p>
              <p className="mb-4"><i className="fas fa-envelope mr-2"></i> contacto@vidaplena.org</p>

              <div className="flex space-x-4 mt-4">
                <i className="fab fa-facebook text-2xl text-green-900"></i>
                <i className="fab fa-instagram text-2xl text-green-900"></i>
                <i className="fab fa-whatsapp text-2xl text-green-900"></i>
              </div>
            </div>

          </div>

        </div>
      </section>

      {/* FOOTER */}
      <footer className="bg-green-900 text-white text-center py-6">
        <p>© 2026 Fundación Vida Plena - Todos los derechos reservados</p>
        <p className="text-sm">Desarrollado con enfoque social y tecnológico</p>
      </footer>
    </>
  );
}
