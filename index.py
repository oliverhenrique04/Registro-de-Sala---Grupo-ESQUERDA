
from __future__ import annotations
import os, bcrypt
from datetime import date, datetime
from contextlib import contextmanager
from typing import Optional, List, Tuple

# ---- DB / ORM ----
from sqlalchemy import (
    create_engine, String, Integer, Date, CheckConstraint,
    ForeignKey, UniqueConstraint, select
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
)

# ---- GUI ----
import tkinter as tk
from tkinter import ttk, messagebox


# CONFIG (seu PostgreSQL local)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:123456@localhost:5432/postgres"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

@contextmanager
def get_session():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def hash_senha_bcrypt(senha_plana: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(senha_plana.encode("utf-8"), salt).decode("utf-8")

def verificar_senha(senha_plana: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(senha_plana.encode("utf-8"), senha_hash.encode("utf-8"))


class Base(DeclarativeBase): pass

class Usuario(Base):
    __tablename__ = "usuario"
    id_usuario: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome:       Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    email:      Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    senha:      Mapped[str] = mapped_column(String(255), nullable=False)  # bcrypt ~60 chars
    tipo:       Mapped[str] = mapped_column(String(20),  nullable=False)  # 'aluno'|'professor'|'admin'
    __table_args__ = (CheckConstraint("tipo IN ('aluno','professor','admin')", name="ck_usuario_tipo"),)
    aluno: Mapped[Optional["Aluno"]] = relationship(back_populates="usuario", uselist=False, cascade="all, delete-orphan")
    professor: Mapped[Optional["Professor"]] = relationship(back_populates="usuario", uselist=False, cascade="all, delete-orphan")
    registros: Mapped[List["Registro"]] = relationship(back_populates="usuario")

class Sala(Base):
    __tablename__ = "sala"
    id_sala:    Mapped[int] = mapped_column(Integer, primary_key=True)
    nome_sala:  Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    capacidade: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("capacidade >= 0", name="ck_sala_capacidade"),)
    registros: Mapped[List["Registro"]] = relationship(back_populates="sala")

class Aluno(Base):
    __tablename__ = "aluno"
    id_aluno:  Mapped[int] = mapped_column(ForeignKey("usuario.id_usuario", ondelete="CASCADE"), primary_key=True)
    matricula: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    usuario: Mapped["Usuario"] = relationship(back_populates="aluno")

class Professor(Base):
    __tablename__ = "professor"
    id_professor: Mapped[int] = mapped_column(ForeignKey("usuario.id_usuario", ondelete="CASCADE"), primary_key=True)
    disciplina:   Mapped[str] = mapped_column(String(120), nullable=False)
    usuario: Mapped["Usuario"] = relationship(back_populates="professor")

class Registro(Base):
    __tablename__ = "registro"
    id_registro:   Mapped[int] = mapped_column(Integer, primary_key=True)
    id_usuario:    Mapped[int] = mapped_column(ForeignKey("usuario.id_usuario", ondelete="CASCADE"), nullable=False)
    id_sala:       Mapped[int] = mapped_column(ForeignKey("sala.id_sala", ondelete="CASCADE"), nullable=False)
    data_registro: Mapped[date] = mapped_column(Date, nullable=False)
    __table_args__ = (UniqueConstraint("id_usuario", "id_sala", "data_registro", name="uq_registro"),)
    usuario: Mapped["Usuario"] = relationship(back_populates="registros")
    sala:    Mapped["Sala"]    = relationship(back_populates="registros")

def criar_tabelas():
    Base.metadata.create_all(bind=engine)

def get_or_create_usuario_aluno(nome: str, email: str, senha_plana: str, matricula: str) -> Tuple[Usuario, bool]:
    with get_session() as s:
        u = s.scalar(select(Usuario).where(Usuario.email == email))
        if u:
            created = False
            if u.tipo != "aluno": u.tipo = "aluno"
            if u.aluno is None: u.aluno = Aluno(matricula=matricula)
            return u, created
        u = Usuario(nome=nome, email=email, senha=hash_senha_bcrypt(senha_plana), tipo="aluno",
                    aluno=Aluno(matricula=matricula))
        s.add(u); s.flush(); s.refresh(u)
        return u, True

def get_or_create_usuario_professor(nome: str, email: str, senha_plana: str, disciplina: str) -> Tuple[Usuario, bool]:
    with get_session() as s:
        u = s.scalar(select(Usuario).where(Usuario.email == email))
        if u:
            created = False
            if u.tipo != "professor": u.tipo = "professor"
            if u.professor is None: u.professor = Professor(disciplina=disciplina)
            return u, created
        u = Usuario(nome=nome, email=email, senha=hash_senha_bcrypt(senha_plana), tipo="professor",
                    professor=Professor(disciplina=disciplina))
        s.add(u); s.flush(); s.refresh(u)
        return u, True

def get_or_create_sala(nome: str, capacidade: int) -> Tuple[Sala, bool]:
    with get_session() as s:
        sala = s.scalar(select(Sala).where(Sala.nome_sala == nome))
        if sala: return sala, False
        sala = Sala(nome_sala=nome, capacidade=capacidade)
        s.add(sala); s.flush(); s.refresh(sala)
        return sala, True

def registrar_idempotente(id_usuario: int, id_sala: int, dia: date) -> Tuple[Registro, bool]:
    with get_session() as s:
        existente = s.scalar(select(Registro).where(
            (Registro.id_usuario == id_usuario) &
            (Registro.id_sala == id_sala) &
            (Registro.data_registro == dia)
        ))
        if existente: return existente, False
        r = Registro(id_usuario=id_usuario, id_sala=id_sala, data_registro=dia)
        s.add(r); s.flush(); s.refresh(r)
        return r, True

def listar_registros(dia: Optional[date] = None):
    with get_session() as s:
        stmt = select(Registro).join(Registro.usuario).join(Registro.sala)
        if dia: stmt = stmt.where(Registro.data_registro == dia)
        rows = s.scalars(stmt).all()
        return [
            dict(
                id_registro=r.id_registro,
                data=r.data_registro.isoformat(),
                usuario=f"{r.usuario.id_usuario} - {r.usuario.nome} ({r.usuario.tipo})",
                sala=f"{r.sala.id_sala} - {r.sala.nome_sala}",
            ) for r in rows
        ]

def listar_usuarios(tipo: Optional[str] = None) -> List[Usuario]:
    with get_session() as s:
        if tipo:
            return s.scalars(select(Usuario).where(Usuario.tipo == tipo).order_by(Usuario.nome)).all()
        return s.scalars(select(Usuario).order_by(Usuario.nome)).all()

def listar_salas() -> List[Sala]:
    with get_session() as s:
        return s.scalars(select(Sala).order_by(Sala.nome_sala)).all()


# FRONTEND GRÁFICO (Tkinter)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cadastro Acadêmico - PostgreSQL")
        self.geometry("760x530")
        self.resizable(False, False)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.tab_aluno = ttk.Frame(nb); nb.add(self.tab_aluno, text="Adicionar Aluno")
        self.tab_prof  = ttk.Frame(nb); nb.add(self.tab_prof,  text="Adicionar Professor")
        self.tab_sala  = ttk.Frame(nb); nb.add(self.tab_sala,  text="Adicionar Sala")
        self.tab_reg   = ttk.Frame(nb); nb.add(self.tab_reg,   text="Registrar Uso")
        self.tab_list  = ttk.Frame(nb); nb.add(self.tab_list,  text="Listar Registros")

        self.build_tab_aluno()
        self.build_tab_prof()
        self.build_tab_sala()
        self.build_tab_registrar()
        self.build_tab_listar()

    
    def build_tab_aluno(self):
        frm = self.tab_aluno
        ttk.Label(frm, text="Nome").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Email").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Senha").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Matrícula").grid(row=3, column=0, sticky="w", padx=6, pady=6)

        self.a_nome = ttk.Entry(frm, width=40)
        self.a_email = ttk.Entry(frm, width=40)
        self.a_senha = ttk.Entry(frm, width=40, show="•")
        self.a_matricula = ttk.Entry(frm, width=40)

        self.a_nome.grid(row=0, column=1, padx=6, pady=6)
        self.a_email.grid(row=1, column=1, padx=6, pady=6)
        self.a_senha.grid(row=2, column=1, padx=6, pady=6)
        self.a_matricula.grid(row=3, column=1, padx=6, pady=6)

        ttk.Button(frm, text="Salvar Aluno", command=self.on_save_aluno).grid(row=4, column=1, sticky="e", padx=6, pady=12)

    def on_save_aluno(self):
        nome = self.a_nome.get().strip()
        email = self.a_email.get().strip()
        senha = self.a_senha.get().strip()
        matricula = self.a_matricula.get().strip()
        if not all([nome, email, senha, matricula]):
            messagebox.showwarning("Campos obrigatórios", "Preencha todos os campos.")
            return
        try:
            _, created = get_or_create_usuario_aluno(nome, email, senha, matricula)
            if created:
                messagebox.showinfo("Sucesso", "✅ Aluno adicionado com sucesso!")
            else:
                messagebox.showinfo("Informação", "ℹ️ Aluno já existia (atualizado se necessário).")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar aluno:\n{type(e).__name__}: {e}")

    
    def build_tab_prof(self):
        frm = self.tab_prof
        ttk.Label(frm, text="Nome").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Email").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Senha").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Disciplina").grid(row=3, column=0, sticky="w", padx=6, pady=6)

        self.p_nome = ttk.Entry(frm, width=40)
        self.p_email = ttk.Entry(frm, width=40)
        self.p_senha = ttk.Entry(frm, width=40, show="•")
        self.p_disc  = ttk.Entry(frm, width=40)

        self.p_nome.grid(row=0, column=1, padx=6, pady=6)
        self.p_email.grid(row=1, column=1, padx=6, pady=6)
        self.p_senha.grid(row=2, column=1, padx=6, pady=6)
        self.p_disc.grid(row=3, column=1, padx=6, pady=6)

        ttk.Button(frm, text="Salvar Professor", command=self.on_save_prof).grid(row=4, column=1, sticky="e", padx=6, pady=12)

    def on_save_prof(self):
        nome = self.p_nome.get().strip()
        email = self.p_email.get().strip()
        senha = self.p_senha.get().strip()
        disciplina = self.p_disc.get().strip()
        if not all([nome, email, senha, disciplina]):
            messagebox.showwarning("Campos obrigatórios", "Preencha todos os campos.")
            return
        try:
            _, created = get_or_create_usuario_professor(nome, email, senha, disciplina)
            if created:
                messagebox.showinfo("Sucesso", "✅ Professor adicionado com sucesso!")
            else:
                messagebox.showinfo("Informação", "ℹ️ Professor já existia (atualizado se necessário).")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar professor:\n{type(e).__name__}: {e}")

    
    def build_tab_sala(self):
        frm = self.tab_sala
        ttk.Label(frm, text="Nome da Sala").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Capacidade").grid(row=1, column=0, sticky="w", padx=6, pady=6)

        self.s_nome = ttk.Entry(frm, width=40)
        self.s_cap  = ttk.Entry(frm, width=40)

        self.s_nome.grid(row=0, column=1, padx=6, pady=6)
        self.s_cap.grid(row=1, column=1, padx=6, pady=6)

        ttk.Button(frm, text="Salvar Sala", command=self.on_save_sala).grid(row=2, column=1, sticky="e", padx=6, pady=12)

    def on_save_sala(self):
        nome = self.s_nome.get().strip()
        cap_txt = self.s_cap.get().strip()
        if not nome or not cap_txt:
            messagebox.showwarning("Campos obrigatórios", "Preencha todos os campos.")
            return
        try:
            capacidade = int(cap_txt)
            _, created = get_or_create_sala(nome, capacidade)
            if created:
                messagebox.showinfo("Sucesso", "✅ Sala adicionada com sucesso!")
            else:
                messagebox.showinfo("Informação", "ℹ️ Sala já existia.")
        except ValueError:
            messagebox.showwarning("Valor inválido", "Capacidade deve ser um número inteiro.")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar sala:\n{type(e).__name__}: {e}")

    
    def build_tab_registrar(self):
        frm = self.tab_reg
        ttk.Label(frm, text="Usuário").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Sala").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(frm, text="Data (AAAA-MM-DD)").grid(row=2, column=0, sticky="w", padx=6, pady=6)

        self.cmb_user = ttk.Combobox(frm, width=45, state="readonly")
        self.cmb_sala = ttk.Combobox(frm, width=45, state="readonly")
        self.e_data   = ttk.Entry(frm, width=20)
        self.e_data.insert(0, date.today().isoformat())

        self.cmb_user.grid(row=0, column=1, padx=6, pady=6, sticky="w")
        self.cmb_sala.grid(row=1, column=1, padx=6, pady=6, sticky="w")
        self.e_data.grid(row=2, column=1, padx=6, pady=6, sticky="w")

        ttk.Button(frm, text="Atualizar Listas", command=self.refresh_user_sala).grid(row=0, column=2, padx=6)
        ttk.Button(frm, text="Registrar Uso", command=self.on_registrar).grid(row=3, column=1, sticky="e", padx=6, pady=12)

        
        self.user_map = {}
        self.sala_map = {}
        self.refresh_user_sala()

    def refresh_user_sala(self):
        users = listar_usuarios()  
        salas = listar_salas()
        self.user_map = {f"{u.id_usuario} - {u.nome} ({u.tipo})": u.id_usuario for u in users}
        self.sala_map = {f"{s.id_sala} - {s.nome_sala}": s.id_sala for s in salas}
        user_labels = list(self.user_map.keys())
        sala_labels = list(self.sala_map.keys())
        self.cmb_user["values"] = user_labels
        self.cmb_sala["values"] = sala_labels
        if user_labels: self.cmb_user.current(0)
        if sala_labels: self.cmb_sala.current(0)

    def on_registrar(self):
        if not self.cmb_user.get() or not self.cmb_sala.get():
            messagebox.showwarning("Seleção obrigatória", "Selecione um usuário e uma sala.")
            return
        try:
            dia = date.fromisoformat(self.e_data.get().strip())
        except Exception:
            messagebox.showwarning("Data inválida", "Use o formato AAAA-MM-DD.")
            return
        id_usuario = self.user_map[self.cmb_user.get()]
        id_sala = self.sala_map[self.cmb_sala.get()]
        try:
            _, created = registrar_idempotente(id_usuario, id_sala, dia)
            if created:
                messagebox.showinfo("Sucesso", "✅ Registro adicionado com sucesso!")
            else:
                messagebox.showinfo("Informação", "ℹ️ Esse registro já existia para a data selecionada.")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao registrar uso:\n{type(e).__name__}: {e}")

    def build_tab_listar(self):
        frm = self.tab_list
        top = ttk.Frame(frm); top.pack(fill="x", pady=6)
        ttk.Label(top, text="Data (AAAA-MM-DD) [opcional]").pack(side="left", padx=6)
        self.l_data = ttk.Entry(top, width=18); self.l_data.pack(side="left", padx=6)
        ttk.Button(top, text="Buscar", command=self.on_listar).pack(side="left", padx=6)

        cols = ("id_registro", "data", "usuario", "sala")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=18)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=170 if c in ("usuario","sala") else 110, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)

    def on_listar(self):
        dia_txt = self.l_data.get().strip()
        dia = None
        if dia_txt:
            try:
                dia = date.fromisoformat(dia_txt)
            except Exception:
                messagebox.showwarning("Data inválida", "Use o formato AAAA-MM-DD.")
                return
        try:
            rows = listar_registros(dia)
            for i in self.tree.get_children():
                self.tree.delete(i)
            for r in rows:
                self.tree.insert("", "end", values=(r["id_registro"], r["data"], r["usuario"], r["sala"]))
            if not rows:
                messagebox.showinfo("Resultado", "Nenhum registro encontrado para o filtro informado.")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao listar registros:\n{type(e).__name__}: {e}")


# MAIN# 

if __name__ == "__main__":
    criar_tabelas()
    app = App()
    app.mainloop()
