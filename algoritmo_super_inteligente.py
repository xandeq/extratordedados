import sys,io,json,re
if sys.platform=='win32':sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')

NOMES=['alexandre','cristina','fernanda','fernando','julia','lucas','luiz','luis','marcelo','maria','paulo','pedro','rafael','sergio','vitor','ana','andre','bruno','daniel','diego','eduardo','fabio','felipe','livia','marly']
SOBRENOMES=['silva','santos','oliveira','ferreira','alves','costa','gomes','lopes','soares','dias','moreira','campos','miranda','farias','sales','coelho','ramos','milanez','lagemann','favero']
PALAVRAS={'contabilidade':'Contabilidade','advocacia':'Advocacia','advogados':'Advogados','consultoria':'Consultoria','clinica':'Clínica','academia':'Academia','cabana':'Cabana','imovel':'Imóvel','imobiliaria':'Imobiliária'}
GENERICOS=['contato','atendimento','info','comercial','suporte']
DOMINIOS_PESSOAIS=['gmail.com','hotmail.com','outlook.com']

def extrair_nome(email):
    if not email or '@' not in email:return "Lead sem nome"
    prefixo,dominio=email.split('@',1)
    dominio_limpo=dominio.replace('.com.br','').replace('.com','').replace('.adv.br','')
    
    # Se prefixo genérico, usar domínio
    if prefixo.lower() in GENERICOS:
        base=dominio_limpo
    elif any(d in dominio.lower() for d in DOMINIOS_PESSOAIS):
        base=prefixo
    else:
        base=dominio_limpo
    
    base=base.lower().strip()
    resultado=[]
    pos=0
    
    # Passar 1: Identificar palavras conhecidas
    while pos<len(base):
        match_found=False
        # Tentar palavras de negócio (mais longas primeiro)
        for pal,cap in sorted(PALAVRAS.items(),key=lambda x:len(x[0]),reverse=True):
            if base[pos:pos+len(pal)]==pal:
                resultado.append(cap)
                pos+=len(pal)
                match_found=True
                break
        if match_found:continue
        
        # Tentar nomes próprios
        for nome in sorted(NOMES+SOBRENOMES,key=len,reverse=True):
            if base[pos:pos+len(nome)]==nome:
                resultado.append(nome.capitalize())
                pos+=len(nome)
                match_found=True
                break
        
        if not match_found:
            # Coletar até próxima palavra conhecida ou fim
            chunk=''
            while pos<len(base):
                chunk+=base[pos]
                pos+=1
                # Checar se próximo pedaço é palavra conhecida
                achou=False
                for pal in list(PALAVRAS.keys())+NOMES+SOBRENOMES:
                    if base[pos:pos+len(pal)]==pal:
                        achou=True
                        break
                if achou:break
            if chunk:resultado.append(chunk.capitalize())
    
    return ' '.join(resultado) if resultado else base.capitalize()

casos=[
    "contato@bateleur.com.br",
    "contato@cabanadoluiz.com.br",
    "contato@cristinamilanez.com",
    "comercial@informatizecontabilidade.com.br",
    "bentoferreira@skyfitacademia.com.br",
    "lagemannconsultoria@gmail.com",
    "contato@faveroadvogados.com.br",
    "atendimento@liviamachado.com",
    "marly@adimovel.com.br"
]

print("TESTES ALGORITMO SUPER INTELIGENTE:\n")
for email in casos:
    nome=extrair_nome(email)
    print(f"✓ {email}\n  → {nome}\n")
